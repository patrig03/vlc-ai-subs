-- audio.lua — audio track/channel discovery and selection

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
        local num = txt:match("0:a:(%d+)") or txt:match("(%d+)")
        if num then return num end
        return "auto"
    end
    if audio_track_dropdown then
        local id = audio_track_dropdown:get_value()
        if not id or id == 1 then return "auto" end
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

-- Probe audio streams via ffprobe (CSV): index,codec_name,channels,language,title
-- Returns array of {idx, codec, chans, lang, title, raw} or nil if detection fails.
function probe_audio_tracks(media_path)
    local ffprobe = "ffprobe"
    local p = io.popen(ffprobe .. " -version 2>&1", "r")
    if not p then
        vlc.msg.info("[AI Subs] ffprobe not found, skipping audio track detection")
        return nil
    end
    local o = p:read("*a")
    p:close()
    if not o or not string.find(o, "ffprobe") then
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

    if out:match("No such file") or out:match("Invalid data") or out:match("Error") then
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
            local parts = {}
            for part in string.gmatch(line .. ",", "([^,]*),") do
                table.insert(parts, part)
            end
            local idx = (parts[1] or ""):gsub("%s+", "")
            if not idx:match("^%d+$") then
                vlc.msg.info("[AI Subs] skipping non-track line: " .. line)
            else
                local codec = parts[2] or "unknown"
                local chans = parts[3] or "?"
                local lang = parts[4] or ""
                local title = ""
                if #parts > 5 then
                    local tparts = {}
                    for i = 5, #parts do table.insert(tparts, parts[i]) end
                    title = table.concat(tparts, ",")
                else
                    title = parts[5] or ""
                end
                if lang == "" then lang = "und" end
                title = title:gsub('^%s*"', ""):gsub('"%s*$', "")
                table.insert(tracks, {idx=idx, codec=codec, chans=chans, lang=lang, title=title, raw=line})
            end
        end
    end
    if #tracks == 0 then return nil end
    return tracks
end

-- Legacy helper kept for compatibility
function refresh_audio_tracks()
    create_dialog()
end
