"""ai_subs package — Whisper transcription backend modules."""

from .constants import (
    SENTENCE_END_PUNCT,
    CLAUSE_PUNCT,
    WEAK_PUNCT,
    TARGET_DURATION,
    SOFT_MAX_DURATION,
    HARD_MAX_DURATION,
    TARGET_CHARS,
    SOFT_MAX_CHARS,
    HARD_MAX_CHARS,
    HARD_MAX_WORDS,
    MIN_DURATION,
    MIN_CHARS,
    MIN_WORDS,
)

__all__ = [
    "SENTENCE_END_PUNCT",
    "CLAUSE_PUNCT",
    "WEAK_PUNCT",
    "TARGET_DURATION",
    "SOFT_MAX_DURATION",
    "HARD_MAX_DURATION",
    "TARGET_CHARS",
    "SOFT_MAX_CHARS",
    "HARD_MAX_CHARS",
    "HARD_MAX_WORDS",
    "MIN_DURATION",
    "MIN_CHARS",
    "MIN_WORDS",
]
