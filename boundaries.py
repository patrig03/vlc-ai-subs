"""
boundaries.py — backwards-compatibility shim.

The segmentation logic now lives in src/aisubs/*. This file re-exports
the public API so existing imports (e.g. `import boundaries`) keep working.
New code should import from `aisubs.segmentation` or `src.aisubs.*`.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from aisubs.constants import (  # noqa: F401,E402
    CLAUSE_PUNCT,
    HARD_MAX_CHARS,
    HARD_MAX_DURATION,
    HARD_MAX_WORDS,
    MIN_CHARS,
    MIN_DURATION,
    MIN_WORDS,
    SENTENCE_END_PUNCT,
    SOFT_MAX_CHARS,
    SOFT_MAX_DURATION,
    TARGET_CHARS,
    TARGET_DURATION,
    WEAK_PUNCT,
)
from aisubs.formatting import break_lines  # noqa: F401,E402
from aisubs.models import SubtitleSegment, Word  # noqa: F401,E402
from aisubs.scoring import (  # noqa: F401,E402
    boundary_score,
    duration_penalty,
    ends_clause,
    ends_sentence,
    ends_weak_punct,
    length_penalty,
    punctuation_score,
    silence_score,
)
from aisubs.segmentation import (  # noqa: F401,E402
    find_best_boundary,
    process_whisper_segment,
    refine_timing,
    segment_words,
    words_from_whisper,
)

__all__ = [
    "Word",
    "SubtitleSegment",
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
    "ends_sentence",
    "ends_clause",
    "ends_weak_punct",
    "silence_score",
    "punctuation_score",
    "boundary_score",
    "duration_penalty",
    "length_penalty",
    "find_best_boundary",
    "segment_words",
    "break_lines",
    "refine_timing",
    "words_from_whisper",
    "process_whisper_segment",
]
