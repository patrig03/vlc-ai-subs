-- compat.lua — VLC version compatibility (3.x / 4.x) and OSD helpers

function get_input_item()
    if vlc.player and vlc.player.item then
        local item = vlc.player.item()
        if item then return item end
    end
    if vlc.input and vlc.input.item then
        local item = vlc.input.item()
        if item then return item end
    end
    return nil
end

function add_subtitle_track(srt_path)
    if vlc.player and vlc.player.add_subtitle then
        vlc.player.add_subtitle(srt_path)
        return true
    end
    if vlc.input and vlc.input.add_subtitle then
        vlc.input.add_subtitle(srt_path)
        return true
    end
    if vlc.object and vlc.object.input then
        local input = vlc.object.input()
        if input and vlc.var and vlc.var.set then
            vlc.var.set(input, "sub-file", srt_path)
            return true
        end
    end
    return false
end

function register_osd()
    if vlc.osd and vlc.osd.channel_register then
        return vlc.osd.channel_register()
    end
    return 1
end

function show_osd(text, duration)
    if not text then return end
    if vlc.osd and vlc.osd.message then
        vlc.osd.message(text, osd_channel, "bottom", duration)
    end
end

function get_media_path()
    local item = get_input_item()
    if not item then return nil, "No media is currently playing." end
    local uri = item:uri()
    if not uri then return nil, "Cannot get media URI." end
    if not string.find(uri, "^file://") then return nil, "Only local files are supported." end

    local path = string.gsub(uri, "^file://", "")
    path = string.gsub(path, "%%(%x%x)", function(hex)
        return string.char(tonumber(hex, 16))
    end)

    if is_windows() then
        path = string.gsub(path, "^/([A-Za-z]:)", "%1")
        path = string.gsub(path, "/", "\\")
    end

    vlc.msg.info("[AI Subs] media path: " .. path)
    return path, nil
end
