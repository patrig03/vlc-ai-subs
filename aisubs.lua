-- aisubs.lua — VLC extension entry point (thin loader)
-- Delegates implementation to lua/*.lua modules for readability.

function descriptor()
    return {
        title = "AI Subs Generator",
        version = "3.3",
        author = "patri",
        url = "https://github.com/voidrlm/vlc-ai-subs",
        shortdesc = "AI subtitle generator",
        description = "Generate subtitles using Whisper AI. Compatible with VLC 3.x and 4.x. Supports audio track/channel selection.",
        capabilities = {"menu"},
    }
end

-- Global UI state (shared across modules)
dlg = nil
model_dropdown = nil
lang_input = nil
task_dropdown = nil
mode_dropdown = nil
status_label = nil
osd_channel = nil
audio_track_dropdown = nil
audio_track_input = nil
audio_channel_dropdown = nil

-- Polling state (set by start_generation, used by poll_progress)
_poll_tmp   = nil
_poll_tmr   = nil
_poll_secs  = 0
_poll_pos   = 0
_poll_count = 0
_poll_pid   = nil
POLL_US     = 1000000

-- ----------------------------------------------------------------
-- Module loader — resolves lua/ submodules relative to this file
-- VLC does not provide the 'debug' library, so we must not index
-- global 'debug' without checking. Use vlc.config fallbacks.
-- ----------------------------------------------------------------
local function script_dir()
    -- 1) Try debug.getinfo if available (works outside VLC, e.g. lua tests)
    if debug and debug.getinfo then
        local source = nil
        if pcall then
            local ok, info = pcall(debug.getinfo, 1, "S")
            if ok and info and info.source then
                source = info.source
            end
        else
            -- pcall not available, try direct (may error, but we are in debug-available env)
            local info = debug.getinfo(1, "S")
            if info then source = info.source end
        end
        if source then
            if source:sub(1, 1) == "@" then
                source = source:sub(2)
            end
            local dir = source:match("^(.*[/\\])")
            if dir then return dir end
        end
    end

    -- 2) VLC fallback: probe known installation directories
    --    aisubs.lua is installed to <userdatadir>/lua/extensions/aisubs.lua
    --    and modules are at <userdatadir>/lua/extensions/lua/*.lua
    --    In VLC playlist scan context 'io' is nil, so guard it.
    local function try_dir(dir)
        if not dir then return nil end
        if not io or not io.open then return nil end
        -- ensure trailing slash
        if dir:sub(-1) ~= "/" and dir:sub(-1) ~= "\\" then
            dir = dir .. "/"
        end
        local probe = dir .. "aisubs.lua"
        local f = io.open(probe, "r")
        if f then
            f:close()
            return dir
        end
        return nil
    end

    if vlc and vlc.config then
        -- try userdatadir (covers ~/.local/share/vlc and flatpak/snap variants)
        if vlc.config.userdatadir then
            local ud = nil
            if pcall then
                local ok, v = pcall(vlc.config.userdatadir)
                if ok then ud = v end
            else
                ud = vlc.config.userdatadir()
            end
            if ud then
                local d = try_dir(ud .. "/lua/extensions/")
                if d then return d end
                d = try_dir(ud .. "/data/vlc/lua/extensions/")
                if d then return d end
            end
        end
        if vlc.config.datadir then
            local dd = nil
            if pcall then
                local ok, v = pcall(vlc.config.datadir)
                if ok then dd = v end
            else
                dd = vlc.config.datadir()
            end
            if dd then
                local d = try_dir(dd .. "/lua/extensions/")
                if d then return d end
            end
        end
        if vlc.config.configdir then
            local cd = nil
            if pcall then
                local ok, v = pcall(vlc.config.configdir)
                if ok then cd = v end
            else
                cd = vlc.config.configdir()
            end
            if cd then
                local d = try_dir(cd .. "/lua/extensions/")
                if d then return d end
            end
        end
    end

    -- 3) Check HOME-based fallbacks (only if os is available - VLC playlist scan has no os)
    if os and os.getenv then
        local home = os.getenv("HOME") or os.getenv("USERPROFILE") or ""
        if home ~= "" then
            local d = try_dir(home .. "/.local/share/vlc/lua/extensions/")
            if d then return d end
            d = try_dir(home .. "/.var/app/org.videolan.VLC/data/vlc/lua/extensions/")
            if d then return d end
            d = try_dir(home .. "/snap/vlc/current/.local/share/vlc/lua/extensions/")
            if d then return d end
            d = try_dir(home .. "/Library/Application Support/org.videolan.vlc/lua/extensions/")
            if d then return d end
        end
        local appdata = os.getenv("APPDATA")
        if appdata then
            local d = try_dir(appdata .. "/vlc/lua/extensions/")
            if d then return d end
            d = try_dir(appdata .. "\\vlc\\lua\\extensions\\")
            if d then return d end
        end
    end

    -- 4) Dev fallback: project root (only if io is available)
    if io and io.open then
        local f = io.open("./aisubs.lua", "r")
        if f then f:close(); return "./" end
        f = io.open("aisubs.lua", "r")
        if f then f:close(); return "./" end
    end

    return nil
end

local modules_loaded = false

local function load_modules()
    -- In VLC playlist scan context, 'io' and 'dofile' are nil.
    -- Don't error during scan; just skip loading and retry at activate().
    if not io or not io.open or not dofile then
        return false
    end

    local dir = script_dir()

    if not dir then
        -- During playlist scan io may be nil already handled, otherwise error for extension
        -- Return false instead of error to allow scan to succeed
        return false
    end

    local modules = {
        "helpers.lua",
        "compat.lua",
        "audio.lua",
        "dialog.lua",
        "polling.lua",
    }

    for _, name in ipairs(modules) do
        local path = dir .. "lua/" .. name

        local ok, err
        if pcall then
            ok, err = pcall(dofile, path)
        else
            -- pcall not available in this VLC build: try direct dofile
            local f = nil
            if io and io.open then
                f = io.open(path, "r")
            end
            if not f then
                ok = false
                err = "file not found: " .. path
            else
                f:close()
                dofile(path)
                ok = true
            end
        end

        if not ok then
            error("Failed to load " .. path .. ": " .. tostring(err))
        end

        if vlc and vlc.msg then
            if vlc.msg.dbg then
                vlc.msg.dbg("[AI Subs] loaded " .. path)
            elseif vlc.msg.info then
                vlc.msg.info("[AI Subs] loaded " .. path)
            end
        end
    end
    modules_loaded = true
    return true
end

-- Try to load at startup (extension context has io), but don't error in playlist scan
load_modules()

-- ----------------------------------------------------------------
-- Lifecycle
-- ----------------------------------------------------------------
function activate()
    if not modules_loaded then
        load_modules()
    end
    create_dialog()
end
function deactivate()
    if _poll_tmr then
        if _poll_tmr.cancel then _poll_tmr:cancel() end
        _poll_tmr = nil
    end
    if _poll_pid and not is_windows() then
        if os and os.execute then
            os.execute("kill " .. tostring(_poll_pid) .. " 2>/dev/null")
        end
        _poll_pid = nil
    end
    if dlg then dlg:delete(); dlg = nil end
end
function close()      deactivate() end

function menu() return {"Generate Subtitles"} end
function trigger_menu(id) if id == 1 then create_dialog() end end
