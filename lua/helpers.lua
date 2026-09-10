-- helpers.lua — low-level utilities (no VLC dependencies beyond vlc.msg)

function shell_quote(str)
    if str == nil then
        return "''"
    end
    str = tostring(str)
    return "'" .. str:gsub("'", "'\\''") .. "'"
end

function is_windows()
    if package and package.config then
        return package.config:sub(1, 1) == "\\"
    end
    if os and os.getenv then
        local os_name = os.getenv("OS") or ""
        if os_name:match("Windows") then return true end
    end
    return false
end

function get_home()
    if os and os.getenv then
        local home = os.getenv("USERPROFILE") or os.getenv("HOME") or ""
        if home ~= "" then return home end
    end
    if vlc and vlc.config and vlc.config.userdatadir then
        local ud = nil
        if pcall then
            local ok, v = pcall(vlc.config.userdatadir)
            if ok then ud = v end
        else
            ud = vlc.config.userdatadir()
        end
        if ud then return ud end
    end
    return ""
end

function get_temp_file()
    local tmp
    -- os.time may also be unavailable in VLC playlist context, guard it
    local t = 0
    if os and os.time then
        t = os.time()
    else
        -- fallback: use math.random if time not available
        t = math.random(1000000)
    end
    if is_windows() then
        if os and os.getenv then
            tmp = os.getenv("TEMP") or os.getenv("TMP")
        end
        if not tmp or tmp == "" then
            tmp = get_home() .. "\\AppData\\Local\\Temp"
        end
        if tmp == "" or tmp == "\\AppData\\Local\\Temp" then
            tmp = "/tmp"
        end
        return tmp .. "\\aisubs_" .. tostring(t) .. ".txt"
    else
        if os and os.getenv then
            tmp = os.getenv("TMPDIR")
        end
        if not tmp or tmp == "" then tmp = "/tmp" end
        return tmp .. "/aisubs_" .. tostring(t) .. ".txt"
    end
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

function set_status(text)
    if status_label then status_label:set_text(text) end
    if dlg then dlg:update() end
end

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
