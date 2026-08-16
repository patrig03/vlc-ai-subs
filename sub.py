#!/usr/bin/env python3
"""
Usage:
    python3 aisubs_whisper.py <media_path>

Arguments:
    media_path  Path to the video/audio file

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


def transcribe_faster_whisper(media_path):
    """Transcribe using faster-whisper (CTranslate2 backend)."""
    from faster_whisper import WhisperModel

    emit({"type": "status", "msg": f"Loading model..."})
    model = WhisperModel("small", device="cuda", compute_type="float16")

    emit({"type": "status", "msg": "Transcribing..."})
    segments_gen, _info = model.transcribe(
        media_path,
        language="ja",
        task="transcribe",
        beam_size=1,
        vad_filter=True,
        vad_parameters={
            "threshold": 0.05,
            "min_silence_duration_ms": 200,
            "speech_pad_ms": 600,
            "min_speech_duration_ms": 50,
        },
    )

    for seg in segments_gen:
        text = seg.text.strip()
        if text:
            yield {"start": seg.start, "end": seg.end, "text": text}



def main():
    global _out_file

    if len(sys.argv) < 2:
        emit({"type": "error", "msg": "Usage: aisubs_whisper.py <media> [out_file]"})
        sys.exit(1)

    media_path = sys.argv[1]

    # Optional output file — Lua passes this so output is captured without shell redirection
    if len(sys.argv) > 2:
        try:
            _out_file = open(sys.argv[2], "w", encoding="utf-8", buffering=1)
        except Exception as e:
            pass  # if we can't open it, stdout-only mode

    if not os.path.isfile(media_path):
        emit({"type": "error", "msg": f"File not found: {media_path}"})
        sys.exit(1)

    # Detect backend
    backend = None
    try:
        import faster_whisper  # noqa: F401
        backend = "faster-whisper"
    except ImportError:
        pass

    segments_iter = transcribe_faster_whisper(media_path)

    # Stream segments and build SRT
    srt_lines = []
    count = 0

    try:
        for seg in segments_iter:
            count += 1
            emit({
                "type": "sub",
                "i": count,
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "text": seg["text"],
            })
            srt_lines.append(
                f"{count}\n"
                f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}\n"
                f"{seg['text']}\n"
            )
    except Exception as e:
        import traceback
        emit({"type": "error", "msg": f"Transcription failed: {e}\n{traceback.format_exc()}"})
        sys.exit(1)

    # Write SRT file next to the media
    base, _ = os.path.splitext(media_path)
    srt_path = base + ".srt"
    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
    except Exception as e:
        emit({"type": "error", "msg": f"Could not write SRT: {e}"})
        sys.exit(1)

    emit({"type": "done", "segments": count, "srt_path": srt_path})

    if _out_file:
        _out_file.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        emit({"type": "error", "msg": str(e) + "\n" + traceback.format_exc()})
        if _out_file:
            _out_file.close()
        sys.exit(1)