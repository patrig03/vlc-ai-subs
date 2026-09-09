#!/usr/bin/env python3
"""
vlc-ai-subs — Whisper transcription backend.

Transcribes audio from a media file using faster-whisper (or openai-whisper
as fallback) and streams results as JSON lines to stdout. Also writes a
standard SRT subtitle file next to the source media.

Usage:
    python3 aisubs.py <media_path> <model> <language> <task> [out_file] [audio_track] [audio_channel]

Arguments:
    media_path    Path to the video/audio file
    model         Whisper model size: tiny, base, small, medium, large
    language      Language code (e.g. en, es, hi) or "auto" for detection
    task          "transcribe" or "translate" (translate outputs English)
    out_file      Optional path to also write JSON lines (used by VLC Lua plugin)
    audio_track   Audio track index: "auto" (default, first track) or 0,1,2...
                  Maps to ffmpeg 0:a:<N>. Uses ffprobe stream index.
    audio_channel Audio channel selection within the track:
                  "auto" (default, mix to mono), "mono"/"mix", "left", "right",
                  "center" or numeric channel index 0,1,2...

Output (stdout):
    One JSON object per line:
      {"type": "status", "msg": "..."}           — progress updates
      {"type": "sub", "i": N, "start": S, "end": E, "text": "..."}  — subtitle
      {"type": "done", "segments": N, "srt_path": "..."}            — finished
      {"type": "error", "msg": "..."}            — fatal error
"""

import sys
import os
import json
import tempfile
import subprocess
import shutil


def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_out_file = None  # optional output file set in main()

def emit(data: dict) -> None:
    """Write a JSON line to stdout and to the output file if set."""
    line = json.dumps(data, ensure_ascii=False)
    print(line, flush=True)
    if _out_file:
        try:
            _out_file.write(line + "\n")
            _out_file.flush()
        except Exception:
            pass


def prepare_audio_source(media_path, audio_track, audio_channel):
    """
    Prepare an audio file for Whisper based on track/channel selection.

    If audio_track is 'auto' and audio_channel is 'auto'/'mix', return the
    original media_path (Whisper/ffmpeg will handle decoding).

    Otherwise use ffmpeg to extract the requested track/channel to a temp
    16 kHz mono WAV which is optimal for Whisper.

    Returns (path_to_use, temp_path_to_cleanup or None).
    """
    track = (audio_track or "auto").strip().lower()
    channel = (audio_channel or "auto").strip().lower()

    # Normalise channel aliases
    if channel in ("", "auto", "default"):
        channel = "auto"
    elif channel in ("mono", "mix", "mixed", "downmix"):
        channel = "mono"
    elif channel in ("left", "l", "channel0", "ch0", "0"):
        # Distinguish numeric track vs channel — channel already normalised
        # Keep numeric channel as left/right only when explicitly channel param
        if channel == "0":
            channel = "left"
        # else left stays left
    elif channel in ("right", "r", "channel1", "ch1", "1"):
        if channel == "1":
            channel = "right"
    elif channel.isdigit():
        # Generic channel index: treat as cN
        pass

    needs_extraction = False
    if track != "auto":
        needs_extraction = True
    if channel != "auto":
        needs_extraction = True

    if not needs_extraction:
        return media_path, None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # No ffmpeg — fall back to original file with warning
        emit({"type": "status", "msg": "ffmpeg not found; using default audio (channel selection ignored)"})
        return media_path, None

    # Create temp wav next to the output or in system temp
    tmp_fd, tmp_wav = tempfile.mkstemp(suffix=".wav", prefix="aisubs_audio_")
    os.close(tmp_fd)

    cmd = [ffmpeg, "-y", "-v", "error", "-i", media_path]

    # Map specific audio track (0-based index of audio streams: 0:a:<idx>)
    if track != "auto":
        try:
            idx = int(track)
            if idx < 0:
                raise ValueError()
            cmd += ["-map", f"0:a:{idx}"]
        except ValueError:
            emit({"type": "error", "msg": f"Invalid audio track '{audio_track}': must be 'auto' or 0,1,2..."})
            try:
                os.remove(tmp_wav)
            except Exception:
                pass
            sys.exit(1)
    # If a channel filter is requested but no explicit track map, ffmpeg will
    # default to the first audio stream — which is the desired "auto" behaviour.

    # Channel extraction / downmix
    if channel == "left":
        cmd += ["-filter:a", "pan=mono|c0=c0"]
    elif channel == "right":
        cmd += ["-filter:a", "pan=mono|c0=c1"]
    elif channel == "center":
        cmd += ["-filter:a", "pan=mono|c0=c2"]
    elif channel.isdigit():
        # Generic channel N -> pan mono from that channel
        cmd += ["-filter:a", f"pan=mono|c0=c{channel}"]
    elif channel == "mono":
        # Explicit mono downmix — ffmpeg does this by default with -ac 1
        pass
    # "auto" -> no filter, keep original channel layout until -ac 1 below

    # Always convert to 16 kHz mono PCM for Whisper
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", tmp_wav]

    emit({"type": "status", "msg": f"Extracting audio track={track} channel={channel} via ffmpeg..."})
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        emit({"type": "error", "msg": "ffmpeg audio extraction timed out"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        emit({"type": "error", "msg": f"Failed to run ffmpeg: {e}"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        emit({"type": "error", "msg": f"ffmpeg failed (track={track} channel={channel}): {err or 'unknown error'}"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)

    if not os.path.isfile(tmp_wav) or os.path.getsize(tmp_wav) == 0:
        emit({"type": "error", "msg": f"ffmpeg produced no output for track={track} channel={channel}"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)

    emit({"type": "status", "msg": f"Audio extracted to temp WAV (track={track} channel={channel})"})
    return tmp_wav, tmp_wav


def transcribe_whisper(media_path, model_name, lang, task):
    """Transcribe using faster-whisper (CTranslate2 backend)."""
    from faster_whisper import WhisperModel

    emit({
        "type": "status", 
        "msg": f"Loading {model_name} model..."
    })

    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    emit({
        "type": "status", 
        "msg": "Transcribing..."
    })

    segments_gen, _info = model.transcribe(
        media_path,
        language=lang,
        task=task,
        beam_size=5,
        
        word_timestamps=True,
        condition_on_previous_text=False,
        vad_filter=False,
    )

    for seg in segments_gen:
        text = seg.text.strip()

        if text:
            yield {
                "start": seg.start,
                "end": seg.end,
                "text": text,
                "words": seg.words,
            }


def main():
    global _out_file

    if len(sys.argv) < 5:
        emit({
            "type": "error", 
            "msg": "Usage: aisubs.py <media> <model> <lang> <task> [out_file]"
        })
        sys.exit(1)

    media_path = sys.argv[1]
    model_name = sys.argv[2]
    language = sys.argv[3] if sys.argv[3] != "auto" else None
    task = sys.argv[4]

    # Optional output file — Lua passes this so output is captured without shell redirection
    # Arg layout: <media> <model> <lang> <task> [out_file] [audio_track] [audio_channel]
    # audio_track: "auto" or 0,1,2... (index among audio streams, 0:a:N)
    # audio_channel: "auto"/"mono"/"left"/"right"/"center" or numeric channel index
    out_file_arg = None
    audio_track = "auto"
    audio_channel = "auto"
    if len(sys.argv) > 5:
        out_file_arg = sys.argv[5]
        try:
            _out_file = open(
                out_file_arg,
                "w",
                encoding="utf-8",
                buffering=1
            )
        except Exception as e:
            pass  # if we can't open it, stdout-only mode
    if len(sys.argv) > 6:
        audio_track = sys.argv[6] or "auto"
    if len(sys.argv) > 7:
        audio_channel = sys.argv[7] or "auto"
    # Handle legacy duplicate tmp_file passed as 6th arg (when Lua passed tmp twice)
    # If audio_track looks like a temp file path, treat as not set
    if audio_track and ("/aisubs_" in audio_track or "\\aisubs_" in audio_track or audio_track.endswith(".txt")):
        audio_track = "auto"
        audio_channel = "auto"

    if not os.path.isfile(media_path):
        emit({
            "type": "error",
            "msg": f"File not found: {media_path}"
        })
        sys.exit(1)

    try:
        import faster_whisper
    except ImportError:
        emit({
            "type": "error",
            "msg": "No Whisper backend found. Run: pip install faster-whisper"
        })
        sys.exit(1)

    # Prepare audio source (ffmpeg extraction if track/channel selection requested)
    transcribe_path = media_path
    temp_audio = None
    try:
        transcribe_path, temp_audio = prepare_audio_source(media_path, audio_track, audio_channel)
    except SystemExit:
        raise
    except Exception as e:
        emit({"type": "error", "msg": f"Audio preparation failed: {e}"})
        sys.exit(1)

    srt_lines = []
    count = 0

    try:
        for seg in transcribe_whisper(transcribe_path, model_name, language, task):
            text = seg["text"]
            words = seg["words"]

            if words:
                words = [
                    w for w in words
                    if w.start is not None and w.end is not None
                ]

            if words:
                start = max(0.0, words[0].start - 0.05)
                end = words[-1].end + 0.05
            else:
                start = seg["start"]
                end = seg["end"]

            count += 1

            emit({
                "type": "sub",
                "i": count,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            })

            srt_lines.append(
                f"{count}\n"
                f"{format_srt_timestamp(start)} --> "
                f"{format_srt_timestamp(end)}\n"
                f"{text}\n"
            )

    except Exception as e:
        import traceback

        emit({
            "type": "error",
            "msg": f"Transcription failed: {e}\n{traceback.format_exc()}"
        })
        if temp_audio:
            try:
                os.remove(temp_audio)
            except Exception:
                pass
        sys.exit(1)
    finally:
        if temp_audio:
            try:
                os.remove(temp_audio)
            except Exception:
                pass

    # Write SRT file next to the media
    base, _ = os.path.splitext(media_path)
    srt_path = base + ".srt"

    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
    except Exception as e:
        emit({
            "type": "error",
            "msg": f"Could not write SRT: {e}"
        })
        sys.exit(1)

    emit({
        "type": "done",
        "segments": count,
        "srt_path": srt_path
    })

    if _out_file:
        _out_file.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        emit({
            "type": "error", 
            "msg": str(e) + "\n" + traceback.format_exc()
        })
        if _out_file:
            _out_file.close()
        sys.exit(1)