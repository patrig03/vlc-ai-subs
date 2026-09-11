"""Whisper transcription using faster-whisper."""

from typing import Iterator

from .protocol import emit


def _is_cuda_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("cublas", "cuda", "cudnn", "libcublas", "cusolver", "cudart"))


def transcribe_whisper(media_path: str, model_name: str, lang: str | None, task: str) -> Iterator[dict]:
    """Transcribe using faster-whisper (CTranslate2 backend) with CUDA→CPU fallback."""
    from faster_whisper import WhisperModel

    emit({"type": "status", "msg": f"Loading {model_name} model..."})

    def _load(device: str, compute: str):
        return WhisperModel(model_name, device=device, compute_type=compute)

    # 1. Try CUDA first, fall back to CPU on load failure
    device = "cuda"
    compute = "float16"
    try:
        model = _load(device, compute)
    except Exception as e:
        if _is_cuda_error(e):
            emit({"type": "status", "msg": f"CUDA load failed ({e}), falling back to CPU..."})
        else:
            emit({"type": "status", "msg": f"CUDA load failed, retrying on CPU: {e}"})
        device = "cpu"
        compute = "int8"
        model = _load(device, compute)

    emit({"type": "status", "msg": "Transcribing..."})

    def _transcribe(m):
        return m.transcribe(
            media_path,
            language=lang,
            task=task,
            beam_size=5,
            word_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=False,
        )

    # 2. Transcribe; if CUDA fails during transcribe/iteration, retry on CPU
    try:
        segments_gen, _info = _transcribe(model)
        for seg in segments_gen:
            text = seg.text.strip()
            if text:
                yield {
                    "start": seg.start,
                    "end": seg.end,
                    "text": text,
                    "words": seg.words,
                }
        return
    except Exception as e:
        if device == "cuda" and _is_cuda_error(e):
            emit({"type": "status", "msg": f"CUDA transcribe failed ({e}), retrying on CPU..."})
            try:
                cpu_model = _load("cpu", "int8")
                segments_gen, _info = _transcribe(cpu_model)
                for seg in segments_gen:
                    text = seg.text.strip()
                    if text:
                        yield {
                            "start": seg.start,
                            "end": seg.end,
                            "text": text,
                            "words": seg.words,
                        }
                return
            except Exception as ce:
                # Re-raise original with context
                raise RuntimeError(f"CPU fallback also failed: {ce}") from e
        raise
