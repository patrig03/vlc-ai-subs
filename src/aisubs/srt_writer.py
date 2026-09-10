"""SRT writing helpers."""

from .formatting import break_lines, format_srt_timestamp
from .protocol import emit


def emit_segment(start: float, end: float, text: str, count: int, srt_lines: list[str]) -> None:
    """Emit a single subtitle segment and append to SRT lines."""
    text = break_lines(text.strip())
    start = max(0.0, start)
    end = max(start + 0.1, end)
    emit(
        {
            "type": "sub",
            "i": count,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
        }
    )
    srt_lines.append(
        f"{count}\n"
        f"{format_srt_timestamp(start)} --> "
        f"{format_srt_timestamp(end)}\n"
        f"{text}\n"
    )
