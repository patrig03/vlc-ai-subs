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
    -- Add random suffix to avoid collisions within same second
    local rnd = 0
    if math and math.random then
        -- seed once
        if not _ai_subs_rand_seeded then
            if os and os.time then pcall(function() math.randomseed(os.time() + math.random(9999)) end) end
            _ai_subs_rand_seeded = true
        end
        rnd = math.random(1000, 9999)
    end
    local suffix = tostring(t) .. "_" .. tostring(rnd)
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
        return tmp .. "\\aisubs_" .. suffix .. ".txt"
    else
        if os and os.getenv then
            tmp = os.getenv("TMPDIR")
        end
        if not tmp or tmp == "" then tmp = "/tmp" end
        return tmp .. "/aisubs_" .. suffix .. ".txt"
    end
end

function parse_json(str)
    if not str then return nil end
    local j = string.match(str, "%b{}")
    if not j then return nil end
    local r = {}
    -- Robust parser: handles escaped strings (\", \\, \n, \t, \/, \r, \b, \uXXXX)
    local i = 1
    local n = #j
    while i <= n do
        local ks, ke, key = j:find('"([^"]+)"%s*:%s*', i)
        if not ks then break end
        i = ke + 1
        if i > n then break end
        local c = j:sub(i, i)
        if c == '"' then
            -- String value
            i = i + 1
            local buf = {}
            while i <= n do
                local ch = j:sub(i, i)
                if ch == "\\" then
                    local nc = j:sub(i + 1, i + 1)
                    if nc == "n" then table.insert(buf, "\n")
                    elseif nc == "t" then table.insert(buf, "\t")
                    elseif nc == "r" then table.insert(buf, "\r")
                    elseif nc == "b" then table.insert(buf, "\b")
                    elseif nc == "f" then table.insert(buf, "\f")
                    elseif nc == '"' then table.insert(buf, '"')
                    elseif nc == "\\" then table.insert(buf, "\\")
                    elseif nc == "/" then table.insert(buf, "/")
                    elseif nc == "u" then
                        local hex = j:sub(i + 2, i + 5)
                        local code = tonumber(hex, 16)
                        if code and code < 128 then
                            table.insert(buf, string.char(code))
                        elseif code then
                            -- best-effort placeholder for non-ascii
                            table.insert(buf, "?")
                        else
                            table.insert(buf, "\\u" .. hex)
                        end
                        i = i + 4 -- extra 4 consumed below
                    else
                        -- Unknown escape, keep literal
                        table.insert(buf, nc)
                    end
                    i = i + 2
                elseif ch == '"' then
                    i = i + 1
                    break
                else
                    table.insert(buf, ch)
                    i = i + 1
                end
            end
            r[key] = table.concat(buf)
        else
            -- Number / boolean / null
            local ns, ne, num = j:find("^%s*([%d%.%-eE+]+)", i)
            if ns then
                r[key] = tonumber(num)
                i = ne + 1
            else
                if j:sub(i, i + 3) == "true" then r[key] = true; i = i + 4
                elseif j:sub(i, i + 4) == "false" then r[key] = false; i = i + 5
                elseif j:sub(i, i + 3) == "null" then r[key] = nil; i = i + 4
                else i = i + 1 end
            end
        end
    end
    -- Fallback for numeric values missed due to string parsing edge (keep compat)
    if next(r) == nil then
        for k, v in string.gmatch(j, '"([^"]+)"%s*:%s*([%d%.%-]+)') do
            if not r[k] then r[k] = tonumber(v) end
        end
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
