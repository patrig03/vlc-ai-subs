function descriptor()
    return {
        title = "AI Subs Generator",
        version = "3.3",
        author = "patri",
        url = "https://github.com/voidrlm/vlc-ai-subs",
        shortdesc = "AI subtitle generator",
        description = "Generate subtitles using Whisper AI"
            .. "Compatible with VLC 3.x and 4.x."
            .. " Supports audio track/channel selection.",
        capabilities = {"menu"},
    }
end

local dlg          = nil
local model_dropdown = nil
local lang_input   = nil
local task_dropdown = nil
local mode_dropdown = nil
local status_label = nil
local osd_channel  = nil
local audio_track_dropdown   = nil
local audio_track_input      = nil
local audio_channel_dropdown = nil

-- Polling state (set by start_generation, used by poll_progress)
local _poll_tmp   = nil
local _poll_model = nil
local _poll_tmr   = nil
local _poll_secs  = 0
local POLL_US     = 3000000  -- poll every 3 seconds

----------------------------------------------------------------
-- Lifecycle
----------------------------------------------------------------

function activate()   create_dialog() end
function deactivate() if dlg then dlg:delete(); dlg = nil end end
function close()      deactivate() end

function menu() return {"Generate Subtitles"} end
function trigger_menu(id) if id == 1 then create_dialog() end end

----------------------------------------------------------------
-- Dialog
----------------------------------------------------------------

function create_dialog()
    if dlg then dlg:delete() end
    dlg = vlc.dialog("AI Subs Generator")

    dlg:add_label("Model:", 1, 2, 1, 1)
    model_dropdown = dlg:add_dropdown(2, 2, 2, 1)
    model_dropdown:add_value("tiny (fastest)", 1)
    model_dropdown:add_value("base (balanced)", 2)
    model_dropdown:add_value("small (accurate)", 3)
    model_dropdown:add_value("medium (very accurate)", 4)
    model_dropdown:add_value("large (best quality)", 5)

    dlg:add_label("Language:", 1, 3, 1, 1)
    lang_input = dlg:add_text_input("auto", 2, 3, 2, 1)

    dlg:add_label("Task:", 1, 4, 1, 1)
    task_dropdown = dlg:add_dropdown(2, 4, 2, 1)
    task_dropdown:add_value("Transcribe (same language)", 1)
    task_dropdown:add_value("Translate to English", 2)

    -- Probe audio tracks from current media (if any) to decide widget type.
    -- If file info is available via ffprobe, show a populated dropdown.
    -- Otherwise fall back to a manual text input so the user can type the
    -- track number (or "auto").
    local detected = nil
    pcall(function()
        local mp, _ = get_media_path()
        if mp then detected = probe_audio_tracks(mp) end
    end)

    if detected and #detected > 0 then
        dlg:add_label("Audio Track:", 1, 5, 1, 1)
        audio_track_dropdown = dlg:add_dropdown(2, 5, 2, 1)
        audio_track_input = nil
        audio_track_dropdown:add_value("Auto (default)", 1)
        for i, t in ipairs(detected) do
            local label
            if t.title and t.title ~= "" and t.title ~= t.codec then
                label = string.format("Track %d: %s (%s, %sch) [0:a:%d]", i, t.title, t.lang, t.chans, i-1)
            else
                label = string.format("Track %d: %s %sch (%s) [0:a:%d]", i, t.codec, t.chans, t.lang, i-1)
            end
            audio_track_dropdown:add_value(label, i + 1)
        end
    else
        -- No file info (no media loaded, ffprobe missing, or probe failed)
        -- -> let the user type the track index manually.
        if detected == nil then
            -- Could be no media; show hint in label
            local mp, _ = get_media_path()
            if not mp then
                dlg:add_label("Audio Track (type number or auto):", 1, 5, 1, 1)
            else
                dlg:add_label("Audio Track (ffprobe unavailable):", 1, 5, 1, 1)
            end
        else
            dlg:add_label("Audio Track (number or auto):", 1, 5, 1, 1)
        end
        audio_track_input = dlg:add_text_input("auto", 2, 5, 2, 1)
        audio_track_dropdown = nil
    end

    dlg:add_label("Audio Channel:", 1, 6, 1, 1)
    audio_channel_dropdown = dlg:add_dropdown(2, 6, 2, 1)
    audio_channel_dropdown:add_value("Auto (mix to mono)", 1)
    audio_channel_dropdown:add_value("Mono (force downmix)", 2)
    audio_channel_dropdown:add_value("Left channel only", 3)
    audio_channel_dropdown:add_value("Right channel only", 4)
    audio_channel_dropdown:add_value("Center channel", 5)

    -- Row 7: Generate + Refresh
    dlg:add_button("Generate", start_generation, 1, 7, 2, 1)
    dlg:add_button("Refresh Tracks", create_dialog, 3, 7, 1, 1)

    local hint = "Ready. Play a media file and click Generate. Use Refresh to reload audio tracks."
    if detected and #detected > 0 then
        hint = string.format("Detected %d audio track(s). Choose one and click Generate.", #detected)
    elseif detected == nil then
        hint = "No media detected. Type track number (0,1..) or 'auto'. Click Refresh after loading file."
    end
    status_label = dlg:add_label(hint, 1, 8, 3, 1)
    dlg:show()
end

----------------------------------------------------------------
-- Dropdown helpers
----------------------------------------------------------------

function get_model_name()
    local models = {"tiny", "base", "small", "medium", "large"}
    local id = model_dropdown:get_value()
    if id and id >= 1 and id <= 5 then return models[id] end
    return "base"
end

function get_task()
    if task_dropdown:get_value() == 2 then return "translate" end
    return "transcribe"
end

function get_audio_track()
    if audio_track_input then
        local txt = audio_track_input:get_text()
        if not txt then return "auto" end
        txt = tostring(txt):gsub("^%s+", ""):gsub("%s+$", ""):lower()
        if txt == "" or txt == "auto" or txt == "default" then return "auto" end
        -- Allow numeric index; strip "0:a:" prefix if user pasted it
        local num = txt:match("0:a:(%d+)") or txt:match("(%d+)")
        if num then return num end
        return "auto"
    end
    if audio_track_dropdown then
        local id = audio_track_dropdown:get_value()
        if not id or id == 1 then return "auto" end
        -- id 2 -> 0, 3 -> 1, etc.
        return tostring(id - 2)
    end
    return "auto"
end

function get_audio_channel()
    if not audio_channel_dropdown then return "auto" end
    local id = audio_channel_dropdown:get_value()
    local map = {
        [1] = "auto",
        [2] = "mono",
        [3] = "left",
        [4] = "right",
        [5] = "center",
        [6] = "0",
        [7] = "1",
        [8] = "2",
    }
    return map[id] or "auto"
end

-- Probe audio streams via ffprobe (CSV output): index,codec_name,channels,language,title
-- Returns array of {idx, codec, chans, lang, title, raw} or nil if detection fails.
function probe_audio_tracks(media_path)
    local ffprobe = "ffprobe"
    -- Quick check: try ffprobe -version; if fails, ffprobe not available
    local ok, _ = pcall(function()
        local p = io.popen(ffprobe .. " -version 2>&1", "r")
        if p then
            local o = p:read("*a")
            p:close()
            if not o or not string.find(o, "ffprobe") then error("not found") end
        else
            error("no popen")
        end
    end)
    if not ok then
        vlc.msg.info("[AI Subs] ffprobe not found, skipping audio track detection")
        return nil
    end

    local cmd = string.format(
        '%s -v error -select_streams a -show_entries stream=index,codec_name,channels:stream_tags=language,title -of csv=p=0 %s 2>&1',
        ffprobe, shell_quote(media_path)
    )
    vlc.msg.info("[AI Subs] probing audio: " .. cmd)
    local pipe = io.popen(cmd, "r")
    if not pipe then return nil end
    local out = pipe:read("*a")
    pipe:close()
    if not out or out == "" then return nil end
    -- ffprobe prints nothing on files with no audio; treat as nil so caller falls back to manual input.
    -- But an empty string already handled above.

    -- If ffprobe wrote an error (e.g. "No such file"), return nil to trigger manual fallback
    if out:match("No such file") or out:match("Invalid data") or out:match("Error") then
        -- But still allow valid CSV even if warning appears; check if any valid line exists
        local has_valid = false
        for _line in string.gmatch(out, "[^\r\n]+") do
            if _line:match("^%s*%d+%s*,") then has_valid = true; break end
        end
        if not has_valid then
            vlc.msg.info("[AI Subs] ffprobe error: " .. out:sub(1,200))
            return nil
        end
    end

    local tracks = {}
    for _line in string.gmatch(out, "[^\r\n]+") do
        local line = _line:gsub("^%s+", ""):gsub("%s+$", "")
        if line ~= "" and not line:match("^%s*$") and not line:match("^ffprobe") then
            -- CSV: index,codec_name,channels,language,title  (language/title may be missing/empty)
            -- Titles may contain commas; ffprobe CSV escapes them. Simple split on comma
            -- will still work for our labels because title is last field; we join extras.
            local parts = {}
            for part in string.gmatch(line .. ",", "([^,]*),") do
                table.insert(parts, part)
            end
            local idx   = (parts[1] or ""):gsub("%s+", "")
            -- Validate: index must be numeric, otherwise it's an error message -> skip
            if not idx:match("^%d+$") then
                vlc.msg.info("[AI Subs] skipping non-track line: " .. line)
            else
                local codec = parts[2] or "unknown"
                local chans = parts[3] or "?"
                local lang  = parts[4] or ""
                -- Join any remaining parts as title (title may contain commas)
                local title = ""
                if #parts > 5 then
                    local tparts = {}
                    for i = 5, #parts do table.insert(tparts, parts[i]) end
                    title = table.concat(tparts, ",")
                else
                    title = parts[5] or ""
                end
                if lang == "" then lang = "und" end
                -- Clean quotes that ffprobe CSV may add
                title = title:gsub('^%s*"', ""):gsub('"%s*$', "")
                table.insert(tracks, {idx=idx, codec=codec, chans=chans, lang=lang, title=title, raw=line})
            end
        end
    end
    if #tracks == 0 then return nil end
    return tracks
end

-- Legacy helper kept for compatibility: recreates the dialog so tracks are
-- re-probed from the currently playing file. Prefer the Refresh button.
function refresh_audio_tracks()
    pcall(create_dialog)
end

----------------------------------------------------------------
-- VLC version compatibility (3.x / 4.x)
----------------------------------------------------------------

function get_input_item()
    local ok, item
    ok, item = pcall(function() return vlc.player.item() end)
    if ok and item then return item end
    ok, item = pcall(function() return vlc.input.item() end)
    if ok and item then return item end
    return nil
end

function add_subtitle_track(srt_path)
    local ok
    ok = pcall(function() vlc.player.add_subtitle(srt_path) end)
    if ok then return true end
    ok = pcall(function() vlc.input.add_subtitle(srt_path) end)
    if ok then return true end
    ok = pcall(function()
        local input = vlc.object.input()
        if input then vlc.var.set(input, "sub-file", srt_path) end
    end)
    return ok
end

function register_osd()
    local ok, ch = pcall(function() return vlc.osd.channel_register() end)
    if ok and ch then return ch end
    return 1
end

function show_osd(text, duration)
    if not text then return end
    local ok = pcall(function()
        vlc.osd.message(text, osd_channel, "bottom", duration)
    end)
    if not ok then
        pcall(function() vlc.osd.message(text, osd_channel) end)
    end
end

----------------------------------------------------------------
-- Path helpers
----------------------------------------------------------------

function shell_quote(str)
    if str == nil then
        return "''"
    end

    str = tostring(str)

    -- Wrap in single quotes. A literal ' becomes '\''.
    return "'" .. str:gsub("'", "'\\''") .. "'"
end

function is_windows()
    return package.config:sub(1, 1) == "\\"
end

function get_home()
    -- USERPROFILE is the standard Windows home directory variable
    local home = os.getenv("USERPROFILE") or os.getenv("HOME") or ""
    return home
end

function get_temp_file()
    local tmp
    if is_windows() then
        tmp = os.getenv("TEMP") or os.getenv("TMP") or (get_home() .. "\\AppData\\Local\\Temp")
        return tmp .. "\\aisubs_" .. os.time() .. ".txt"
    else
        tmp = os.getenv("TMPDIR") or "/tmp"
        return tmp .. "/aisubs_" .. os.time() .. ".txt"
    end
end

----------------------------------------------------------------
-- Media path
----------------------------------------------------------------

function get_media_path()
    local item = get_input_item()
    if not item then return nil, "No media is currently playing." end
    local uri = item:uri()
    if not uri then return nil, "Cannot get media URI." end
    if not string.find(uri, "^file://") then return nil, "Only local files are supported." end

    -- Strip file:// prefix
    local path = string.gsub(uri, "^file://", "")

    -- URL-decode percent-encoded characters
    path = string.gsub(path, "%%(%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end)

    -- On Windows, VLC produces file:///C:/path → after strip → /C:/path
    -- Remove the leading slash before the drive letter
    if is_windows() then
        path = string.gsub(path, "^/([A-Za-z]:)", "%1")
        path = string.gsub(path, "/", "\\")
    end

    vlc.msg.info("[AI Subs] media path: " .. path)
    return path, nil
end

----------------------------------------------------------------
-- Locate the Python backend script
----------------------------------------------------------------

function find_script()
    local home = get_home()
    local candidates = {}

    -- Search for the Python backend. Check installed location first, then dev path.
    if is_windows() then
        local appdata = os.getenv("APPDATA") or (home .. "\\AppData\\Roaming")
        table.insert(candidates, appdata .. "\\vlc-ai-subs\\aisubs.py")
        -- Also check next to the Lua extension (if Python was copied there)
        table.insert(candidates, appdata .. "\\vlc\\lua\\extensions\\aisubs.py")
    else
        table.insert(candidates, home .. "/.local/share/vlc-ai-subs/aisubs.py")
        table.insert(candidates, home .. "/Projects/ai-subs/aisubs.py")
        -- Fallback: check VLC extension dir itself (some installs copy py there)
        table.insert(candidates, home .. "/.local/share/vlc/lua/extensions/aisubs.py")
        -- Flatpak / snap user data
        table.insert(candidates, home .. "/.var/app/org.videolan.VLC/data/vlc-ai-subs/aisubs.py")
        table.insert(candidates, home .. "/snap/vlc/current/.local/share/vlc-ai-subs/aisubs.py")
    end
    -- Last resort: try current directory / script-relative (useful for dev)
    table.insert(candidates, "./aisubs.py")
    table.insert(candidates, "aisubs.py")

    for _, path in ipairs(candidates) do
        local f = io.open(path, "r")
        if f then f:close(); return path end
    end
    return nil
end

-- find a Python interpreter to run launch.py.
-- Priority: bundled venv → explicit AI_SUBS_PYTHON → system python.
function find_python_for_launcher(script_dir)
    local sep = is_windows() and "\\" or "/"

    -- plugin-bundled venv
    local p = script_dir .. sep .. "venv" .. sep .. "bin" .. sep .. "python3"
    local f = io.open(p, "r")
    if f then f:close(); return p end

    p = script_dir .. sep .. "venv" .. sep .. "Scripts" .. sep .. "python.exe"
    f = io.open(p, "r")
    if f then f:close(); return p end

    -- explicit configured Python (validated to be an existing file)
    local explicit = os.getenv("AI_SUBS_PYTHON")
    if explicit then
        f = io.open(explicit, "r")
        if f then f:close(); return explicit end
    end

    -- last resort: system python
    return is_windows() and "python" or "python3"
end

---------------------------------------------------------------
-- Main entry
---------------------------------------------------------------

function start_generation()
    
    -- Cancel any in-progress transcription
    if _poll_tmr then
        pcall(function() _poll_tmr:cancel() end)
        _poll_tmr = nil
    end
    
    local media_path, err = get_media_path()
    if not media_path then
        set_status("Error: " .. err)
        return
    end
    
    local script = find_script()
    if not script then
        set_status("Error: aisubs.py not found. Run setup.sh first.")
        return
    end
    
    local script_dir = string.match(script, "(.+)[/\\][^/\\]+$") or "."
    local launch_script = script_dir .. (is_windows() and "\\" or "/") .. "launch.py"
    local model     = get_model_name()
    local language  = lang_input:get_text() or "auto"
    local task      = get_task()
    local tmp_file  = get_temp_file()
    local audio_track   = get_audio_track()
    local audio_channel = get_audio_channel()
    
    -- Write sentinel so we can detect if Python started writing
    local test_f = io.open(tmp_file, "w")
    if not test_f then
        set_status("Error: cannot write to temp dir: " .. tmp_file)
        return
    end
    test_f:write("init\n")
    test_f:close()

    local launch_python = find_python_for_launcher(script_dir)

    local cmd
    if is_windows() then
        -- Windows: use wscript to run launch.py in background
        local vbs_file = string.gsub(tmp_file, "%.txt$", ".vbs")
        local vf = io.open(vbs_file, "w")
        if not vf then
            set_status("Error: cannot write helper file: " .. vbs_file)
            return
        end
        local raw_cmd = string.format('"%s" -u "%s" "%s" "%s" "%s" "%s" "%s" "%s" "%s"',
            launch_python, launch_script, media_path, model, language, task, tmp_file, audio_track, audio_channel)
        vf:write('Set sh = CreateObject("WScript.Shell")\n')
        vf:write('sh.Run "' .. raw_cmd:gsub('"', '""') .. '", 0, False\n')
        vf:close()
        cmd = 'wscript.exe /nologo "' .. vbs_file .. '"'
    else
        -- Unix: run launch.py asynchronously through bash
        local inner_cmd = string.format(
            '%s -u %s %s %s %s %s %s %s %s',
            shell_quote(launch_python),
            shell_quote(launch_script),
            shell_quote(media_path),
            shell_quote(model),
            shell_quote(language),
            shell_quote(task),
            shell_quote(tmp_file),
            shell_quote(audio_track),
            shell_quote(audio_channel)
        )

        cmd = string.format(
            'bash -c %s &',
            shell_quote(inner_cmd)
        )

        vlc.msg.info("[AI Subs] cmd: " .. cmd)
    end
    
    vlc.msg.info("[AI Subs] python: " .. launch_python)
    vlc.msg.info("[AI Subs] media:  " .. media_path)
    vlc.msg.info("[AI Subs] tmp:    " .. tmp_file)
    vlc.msg.info("[AI Subs] audio_track: " .. audio_track .. " audio_channel: " .. audio_channel)


    local pipe, err = io.popen(cmd, "r")

    if not pipe then
        vlc.msg.err("[AI Subs] io.popen FAILED: " .. tostring(err))
        set_status("popen failed: " .. tostring(err))
        return
    end

    vlc.msg.info("[AI Subs] io.popen succeeded")

    local output = pipe:read("*a")

    vlc.msg.info("[AI Subs] Process output:")
    vlc.msg.info(output ~= "" and output or "(no output)")

    local ok, reason, code = pipe:close()

    vlc.msg.info(string.format(
        "[AI Subs] Process finished: ok=%s reason=%s code=%s",
        tostring(ok),
        tostring(reason),
        tostring(code)
    ))

    -- Poll tmp_file every 3 s; VLC's thread stays free the whole time
    _poll_tmp   = tmp_file
    _poll_secs  = 0
    set_status("Transcribing... please wait")
    _poll_tmr = vlc.timer(poll_progress)
    _poll_tmr:schedule(POLL_US)
end

----------------------------------------------------------------
-- Polling callback — called by vlc.timer every POLL_US microseconds
----------------------------------------------------------------

function poll_progress()
    _poll_secs = _poll_secs + (POLL_US / 1000000)

    local f = io.open(_poll_tmp, "r")
    if not f then
        -- Temp file gone — shouldn't happen; keep waiting
        set_status(string.format("Transcribing... %ds", _poll_secs))
        _poll_tmr:schedule(POLL_US)
        return
    end

    local last_line = nil
    for line in f:lines() do last_line = line end
    f:close()

    if not last_line or last_line == "init" then
        -- Python hasn't written output yet
        set_status(string.format("Loading model / starting... %ds", _poll_secs))
        _poll_tmr:schedule(POLL_US)
        return
    end

    local d = parse_json(last_line)
    if d and (d.type == "done" or d.type == "error") then
        -- Python finished — process results
        _poll_tmr = nil
        process_results(_poll_tmp)
    else
        set_status(string.format("Transcribing with... %ds", _poll_secs))
        _poll_tmr:schedule(POLL_US)
    end
end

----------------------------------------------------------------
-- Process results from temp file
----------------------------------------------------------------

function process_results(tmp_file)
    local f = io.open(tmp_file, "r")
    if not f then
        set_status("Error: Whisper produced no output. Check VLC logs.")
        return
    end

    local srt_path  = nil
    local seg_count = 0

    for line in f:lines() do
        local d = parse_json(line)
        if d then
            if d.type == "error" then
                set_status("Error: " .. (d.msg or "unknown"))
                f:close()
                pcall(function() os.remove(tmp_file) end)
                return
            elseif d.type == "sub" then
                seg_count = seg_count + 1
            elseif d.type == "done" then
                srt_path  = d.srt_path
                seg_count = d.segments or seg_count
            end
        end
    end
    f:close()
    pcall(function() os.remove(tmp_file) end)

    if not srt_path then
        set_status("Error: transcription failed. Check VLC logs for details.")
        return
    end

    load_subtitle(srt_path)
    set_status("Done! " .. seg_count .. " segments. Subtitles loaded.")
end

----------------------------------------------------------------
-- Helpers
----------------------------------------------------------------

function load_subtitle(srt_path)
    local f = io.open(srt_path, "r")
    if not f then return end
    f:close()
    if add_subtitle_track(srt_path) then
        vlc.msg.info("[AI Subs] Loaded: " .. srt_path)
    else
        vlc.msg.warn("[AI Subs] Auto-load failed. Add manually: " .. srt_path)
    end
end

function set_status(text)
    if status_label then status_label:set_text(text) end
    if dlg then dlg:update() end
end

function parse_json(str)
    if not str then return nil end
    local j = string.match(str, "%b{}")
    if not j then return nil end
    local r = {}
    for k, v in string.gmatch(j, '"([^"]+)"%s*:%s*"(.-)"') do
        v = string.gsub(v, "\\n", "\n")
        v = string.gsub(v, "\\t", "\t")
        v = string.gsub(v, '\\"', '"')
        v = string.gsub(v, "\\\\", "\\")
        r[k] = v
    end
    for k, v in string.gmatch(j, '"([^"]+)"%s*:%s*([%d%.%-]+)') do
        if not r[k] then r[k] = tonumber(v) end
    end
    return r
end
