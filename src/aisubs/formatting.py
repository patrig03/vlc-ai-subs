"""SRT and line-break formatting utilities."""

from .constants import TARGET_CHARS


def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def break_lines(text: str, max_chars: int = TARGET_CHARS) -> str:
    """Word-wrap text to max_chars, inserting \\n breaks."""
    words = text.split()
    if not words:
        return text

    if len(text) <= max_chars:
        return text

    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0

    for word in words:
        word_len = len(word)
        if current_len + word_len + (1 if current_line else 0) <= max_chars:
            current_line.append(word)
            current_len += word_len + (1 if current_line else 0)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_len = word_len

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)
