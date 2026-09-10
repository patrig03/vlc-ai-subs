"""Whisper transcription using faster-whisper."""

from typing import Iterator

from .protocol import emit


def transcribe_whisper(media_path: str, model_name: str, lang: str | None, task: str) -> Iterator[dict]:
    """Transcribe using faster-whisper (CTranslate2 backend)."""
    from faster_whisper import WhisperModel

    emit({"type": "status", "msg": f"Loading {model_name} model..."})

    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    emit({"type": "status", "msg": "Transcribing..."})

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
