"""CLI entry point for aisubs transcription.

Usage:
    python -m aisubs.cli <media_path> <model> <language> <task> [out_file] [audio_track] [audio_channel]
Or via the root wrapper:
    python aisubs.py <media_path> <model> <language> <task> [out_file] [audio_track] [audio_channel]
"""

import os
import sys

from .audio import prepare_audio_source
from .formatting import break_lines, format_srt_timestamp
from .protocol import emit, set_output_file
from .segmentation import refine_timing, segment_words, words_from_whisper
from .transcription import transcribe_whisper


def _parse_args(argv: list[str]) -> dict:
    if len(argv) < 5:
        emit({"type": "error", "msg": "Usage: aisubs.py <media> <model> <lang> <task> [out_file] [audio_track] [audio_channel]"})
        sys.exit(1)

    media_path = argv[1]
    model_name = argv[2]
    language = argv[3] if argv[3] != "auto" else None
    task = argv[4]

    out_file_arg = None
    audio_track = "auto"
    audio_channel = "auto"

    if len(argv) > 5:
        out_file_arg = argv[5]
        try:
            f = open(out_file_arg, "w", encoding="utf-8", buffering=1)
            set_output_file(f)
        except Exception:
            pass  # stdout-only mode

    if len(argv) > 6:
        audio_track = argv[6] or "auto"
    if len(argv) > 7:
        audio_channel = argv[7] or "auto"

    # Legacy: handle duplicate tmp_file passed as 6th arg
    if audio_track and ("/aisubs_" in audio_track or "\\aisubs_" in audio_track or audio_track.endswith(".txt")):
        audio_track = "auto"
        audio_channel = "auto"

    return {
        "media_path": media_path,
        "model_name": model_name,
        "language": language,
        "task": task,
        "out_file_arg": out_file_arg,
        "audio_track": audio_track,
        "audio_channel": audio_channel,
    }


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv

    args = _parse_args(argv)
    media_path = args["media_path"]
    model_name = args["model_name"]
    language = args["language"]
    task = args["task"]
    audio_track = args["audio_track"]
    audio_channel = args["audio_channel"]

    if not os.path.isfile(media_path):
        emit({"type": "error", "msg": f"File not found: {media_path}"})
        sys.exit(1)

    try:
        import faster_whisper  # noqa: F401  — check availability
    except ImportError:
        emit({"type": "error", "msg": "No Whisper backend found. Run: pip install faster-whisper"})
        sys.exit(1)

    # Prepare audio source (ffmpeg extraction if needed)
    transcribe_path = media_path
    temp_audio = None
    try:
        transcribe_path, temp_audio = prepare_audio_source(media_path, audio_track, audio_channel)
    except SystemExit:
        raise
    except Exception as e:
        emit({"type": "error", "msg": f"Audio preparation failed: {e}"})
        sys.exit(1)

    srt_lines: list[str] = []
    count = 0

    try:
        for seg in transcribe_whisper(transcribe_path, model_name, language, task):
            text = seg["text"]
            words = seg["words"]

            segmented = False
            if words:
                try:
                    our_words = words_from_whisper(words)
                except Exception:
                    our_words = []

                if our_words:
                    try:
                        sub_segments = segment_words(our_words)
                        sub_segments = refine_timing(sub_segments)
                    except Exception:
                        sub_segments = []

                    if sub_segments:
                        for sub in sub_segments:
                            seg_text = break_lines(sub.text)
                            seg_start = sub.start
                            seg_end = sub.end
                            count += 1
                            emit(
                                {
                                    "type": "sub",
                                    "i": count,
                                    "start": round(max(0.0, seg_start), 3),
                                    "end": round(max(seg_start + 0.1, seg_end), 3),
                                    "text": seg_text,
                                }
                            )
                            srt_lines.append(
                                f"{count}\n"
                                f"{format_srt_timestamp(max(0.0, seg_start))} --> "
                                f"{format_srt_timestamp(max(seg_start + 0.1, seg_end))}\n"
                                f"{seg_text}\n"
                            )
                        segmented = True

            if segmented:
                continue

            # Fallback: no usable word timestamps — use original whisper timing
            if words:
                words = [w for w in words if w.start is not None and w.end is not None]

            if words:
                start = max(0.0, words[0].start - 0.05)
                end = words[-1].end + 0.05
            else:
                start = seg["start"]
                end = seg["end"]

            text = break_lines(text)
            count += 1
            emit(
                {
                    "type": "sub",
                    "i": count,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                }
            )
            srt_lines.append(f"{count}\n" f"{format_srt_timestamp(start)} --> " f"{format_srt_timestamp(end)}\n" f"{text}\n")

    except Exception as e:
        import traceback

        emit({"type": "error", "msg": f"Transcription failed: {e}\n{traceback.format_exc()}"})
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
        emit({"type": "error", "msg": f"Could not write SRT: {e}"})
        sys.exit(1)

    emit({"type": "done", "segments": count, "srt_path": srt_path})

    # Close output file if set
    from . import protocol as _proto

    if _proto._out_file:
        try:
            _proto._out_file.close()
        except Exception:
            pass
        set_output_file(None)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        emit({"type": "error", "msg": str(e) + "\n" + traceback.format_exc()})
        from . import protocol as _proto

        if _proto._out_file:
            try:
                _proto._out_file.close()
            except Exception:
                pass
        sys.exit(1)
