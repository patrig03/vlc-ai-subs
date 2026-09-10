"""Audio extraction via ffmpeg for track / channel selection."""

import os
import shutil
import subprocess
import sys
import tempfile

from .protocol import emit


def _normalise_channel(channel: str) -> str:
    channel = (channel or "auto").strip().lower()
    if channel in ("", "auto", "default"):
        return "auto"
    if channel in ("mono", "mix", "mixed", "downmix"):
        return "mono"
    if channel in ("left", "l", "channel0", "ch0", "0"):
        if channel == "0":
            return "left"
        return "left"
    if channel in ("right", "r", "channel1", "ch1", "1"):
        if channel == "1":
            return "right"
        return "right"
    if channel.isdigit():
        return channel
    return channel


def prepare_audio_source(
    media_path: str,
    audio_track: str,
    audio_channel: str,
) -> tuple[str, str | None]:
    """
    Prepare an audio file for Whisper based on track/channel selection.

    If both are 'auto', return the original path.  Otherwise use ffmpeg
    to extract the requested track/channel to a temp 16 kHz mono WAV.
    Returns (path_to_use, temp_path_to_cleanup or None).
    """
    track = (audio_track or "auto").strip().lower()
    channel = _normalise_channel(audio_channel)

    needs_extraction = track != "auto" or channel != "auto"

    if not needs_extraction:
        return media_path, None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        emit({"type": "status", "msg": "ffmpeg not found; using default audio (channel selection ignored)"})
        return media_path, None

    tmp_fd, tmp_wav = tempfile.mkstemp(suffix=".wav", prefix="aisubs_audio_")
    os.close(tmp_fd)

    cmd = [ffmpeg, "-y", "-v", "error", "-i", media_path]

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

    if channel == "left":
        cmd += ["-filter:a", "pan=mono|c0=c0"]
    elif channel == "right":
        cmd += ["-filter:a", "pan=mono|c0=c1"]
    elif channel == "center":
        cmd += ["-filter:a", "pan=mono|c0=c2"]
    elif channel.isdigit():
        cmd += ["-filter:a", f"pan=mono|c0=c{channel}"]
    elif channel == "mono":
        pass  # explicit mono downmix via -ac 1 below

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
