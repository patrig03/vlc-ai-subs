#!/usr/bin/env python3
"""
vlc-ai-subs — Whisper transcription backend.

Transcribes audio from a media file using faster-whisper (or openai-whisper
as fallback) and streams results as JSON lines to stdout. Also writes a
standard SRT subtitle file next to the source media.

Usage:
    python3 aisubs.py <media_path> <model> <language> <task>

Arguments:
    media_path  Path to the video/audio file
    model       Whisper model size: tiny, base, small, medium, large
    language    Language code (e.g. en, es, hi) or "auto" for detection
    task        "transcribe" or "translate" (translate outputs English)

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
    if len(sys.argv) > 5:
        try:
            _out_file = open(
                sys.argv[5], 
                "w", 
                encoding="utf-8", 
                buffering=1
            )
        except Exception as e:
            pass  # if we can't open it, stdout-only mode

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

    srt_lines = []
    count = 0

    try:
        for seg in transcribe_whisper(media_path, model_name, language, task):
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
        sys.exit(1)

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