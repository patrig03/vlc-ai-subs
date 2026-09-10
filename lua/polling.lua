-- polling.lua — subprocess spawning, polling, and result processing

function find_script()
    local home = get_home()
    local candidates = {}

    if is_windows() then
        local appdata = ""
        if os and os.getenv then
            appdata = os.getenv("APPDATA") or ""
        end
        if appdata == "" then appdata = home .. "\\AppData\\Roaming" end
        table.insert(candidates, appdata .. "\\vlc-ai-subs\\aisubs.py")
        table.insert(candidates, appdata .. "\\vlc\\lua\\extensions\\aisubs.py")
    else
        table.insert(candidates, home .. "/.local/share/vlc-ai-subs/aisubs.py")
        table.insert(candidates, home .. "/Projects/ai-subs/aisubs.py")
        table.insert(candidates, home .. "/.local/share/vlc/lua/extensions/aisubs.py")
        table.insert(candidates, home .. "/.var/app/org.videolan.VLC/data/vlc-ai-subs/aisubs.py")
        table.insert(candidates, home .. "/snap/vlc/current/.local/share/vlc-ai-subs/aisubs.py")
    end
    table.insert(candidates, "./aisubs.py")
    table.insert(candidates, "aisubs.py")

    for _, path in ipairs(candidates) do
        local f = io.open(path, "r")
        if f then f:close(); return path end
    end
    return nil
end

function find_python_for_launcher(script_dir)
    local sep = is_windows() and "\\" or "/"
    local p = script_dir .. sep .. "venv" .. sep .. "bin" .. sep .. "python3"
    local f = io.open(p, "r")
    if f then f:close(); return p end

    p = script_dir .. sep .. "venv" .. sep .. "Scripts" .. sep .. "python.exe"
    f = io.open(p, "r")
    if f then f:close(); return p end

    local explicit = nil
    if os and os.getenv then
        explicit = os.getenv("AI_SUBS_PYTHON")
    end
    if explicit then
        f = io.open(explicit, "r")
        if f then f:close(); return explicit end
    end

    return is_windows() and "python" or "python3"
end

function start_generation()
    if _poll_tmr then
        if _poll_tmr.cancel then _poll_tmr:cancel() end
        _poll_tmr = nil
    end
    _poll_pid = nil

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

    local test_f = io.open(tmp_file, "w")
    if not test_f then
        set_status("Error: cannot write to temp dir: " .. tmp_file)
        return
    end
    test_f:close()

    local launch_python = find_python_for_launcher(script_dir)

    vlc.msg.info("[AI Subs] python: " .. launch_python)
    vlc.msg.info("[AI Subs] media:  " .. media_path)
    vlc.msg.info("[AI Subs] tmp:    " .. tmp_file)
    vlc.msg.info("[AI Subs] audio_track: " .. audio_track .. " audio_channel: " .. audio_channel)

    _poll_tmp   = tmp_file
    _poll_secs  = 0
    _poll_pos   = 0
    _poll_count = 0
    _poll_pid   = nil

    if is_windows() then
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
        local cmd = 'wscript.exe /nologo "' .. vbs_file .. '"'
        vlc.msg.info("[AI Subs] cmd: " .. cmd)
        local ok = nil
        if os and os.execute then
            ok = os.execute(cmd)
        end
        vlc.msg.info("[AI Subs] wscript spawn ok=" .. tostring(ok))
    else
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
        local cmd = inner_cmd .. " > /dev/null 2>&1 < /dev/null & echo $!"
        vlc.msg.info("[AI Subs] cmd: " .. cmd)
        if not (io and io.popen) then
            vlc.msg.err("[AI Subs] io.popen not available")
            set_status("Error: io.popen not available in this VLC build")
            return
        end
        local pipe = io.popen(cmd, "r")
        if not pipe then
            vlc.msg.err("[AI Subs] io.popen FAILED for detached cmd")
            set_status("Error: failed to spawn transcription process")
            return
        end
        local pid = pipe:read("*l")
        pipe:close()
        if pid then pid = pid:gsub("%s+", "") end
        if pid and pid:match("^%d+$") then
            _poll_pid = pid
            vlc.msg.info("[AI Subs] spawned pid=" .. pid)
        else
            vlc.msg.info("[AI Subs] spawned (no pid captured)")
        end
    end

    set_status("Transcribing... please wait (0s)")
    _poll_tmr = vlc.timer(poll_progress)
    _poll_tmr:schedule(POLL_US)
end

function poll_progress()
    if not _poll_tmp then
        vlc.msg.warn("[AI Subs] poll: no _poll_tmp")
        return
    end
    _poll_secs = _poll_secs + (POLL_US / 1000000)
    vlc.msg.info(string.format("[AI Subs] poll tick %ds count=%d tmp=%s", _poll_secs, _poll_count or 0, tostring(_poll_tmp)))

    local f = io.open(_poll_tmp, "r")
    if not f then
        vlc.msg.warn("[AI Subs] poll: cannot open " .. tostring(_poll_tmp))
        if _poll_secs > 30 then
            set_status("Error: temp file lost. Check VLC logs.")
            if _poll_tmr then
                if _poll_tmr.cancel then _poll_tmr:cancel() end
                _poll_tmr=nil
            end
            _poll_tmp = nil
            return
        end
        set_status(string.format("Loading model / starting... %ds", _poll_secs))
        if _poll_tmr and _poll_tmp then
            _poll_tmr:schedule(POLL_US)
        end
        return
    end

    local last_status = nil
    local last_line = nil
    local has_data = false
    local saw_done = false
    local saw_error = false
    local seg_in_file = 0

    for line in f:lines() do
        last_line = line
        if line ~= "" and line ~= "init" then
            has_data = true
            local d = parse_json(line)
            if d then
                if d.type == "status" and d.msg then
                    last_status = d.msg
                elseif d.type == "sub" then
                    seg_in_file = seg_in_file + 1
                elseif d.type == "error" then
                    saw_error = true
                elseif d.type == "done" then
                    saw_done = true
                    if d.segments then seg_in_file = d.segments end
                end
            end
        end
    end
    f:close()

    if seg_in_file > _poll_count then _poll_count = seg_in_file end
    vlc.msg.info(string.format("[AI Subs] poll last_status=%s segs=%d done=%s err=%s", tostring(last_status), _poll_count, tostring(saw_done), tostring(saw_error)))

    if saw_error or saw_done then
        if _poll_tmr then
            if _poll_tmr.cancel then _poll_tmr:cancel() end
            _poll_tmr=nil
        end
        _poll_pid = nil
        process_results(_poll_tmp)
        return
    end

    if not has_data then
        set_status(string.format("Loading model / starting... %ds", _poll_secs))
    elseif last_status then
        set_status(string.format("%s (%ds) — %d segments", last_status, _poll_secs, _poll_count))
    elseif _poll_count > 0 then
        set_status(string.format("Transcribing... %d segments (%ds)", _poll_count, _poll_secs))
    else
        set_status(string.format("Transcribing... %ds", _poll_secs))
    end

    if _poll_tmr and _poll_tmp then
        _poll_tmr:schedule(POLL_US)
    end
end

function process_results(tmp_file)
    local f = io.open(tmp_file, "r")
    if not f then
        set_status("Error: Whisper produced no output. Check VLC logs.")
        _poll_tmp = nil
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
                if os and os.remove then
                    os.remove(tmp_file)
                    os.remove(tmp_file:gsub("%.txt$",".vbs"))
                    os.remove(tmp_file..".log")
                end
                _poll_tmp = nil
                _poll_pid = nil
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
    if os and os.remove then
        os.remove(tmp_file)
        os.remove(tmp_file:gsub("%.txt$",".vbs"))
        os.remove(tmp_file..".log")
    end
    _poll_tmp = nil
    _poll_pid = nil

    if not srt_path then
        set_status("Error: transcription failed. Check VLC logs for details.")
        return
    end

    load_subtitle(srt_path)
    set_status("Done! " .. seg_count .. " segments. Subtitles loaded.")
end
