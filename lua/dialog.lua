-- dialog.lua — VLC dialog creation and widget helpers

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

    local detected = nil
    local mp, _ = get_media_path()
    if mp then
        detected = probe_audio_tracks(mp)
    end

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
        if detected == nil then
            local mp2, _ = get_media_path()
            if not mp2 then
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
