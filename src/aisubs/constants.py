"""Tunable constants for subtitle segmentation.

These control the trade-off between readability (short lines, 4s target)
and fidelity to speech pauses / punctuation.
"""

SENTENCE_END_PUNCT = {".", "?", "!"}
CLAUSE_PUNCT = {";", ":"}
WEAK_PUNCT = {",", "—", "…"}

TARGET_DURATION = 4.0
SOFT_MAX_DURATION = 6.0
HARD_MAX_DURATION = 8.0

TARGET_CHARS = 42
SOFT_MAX_CHARS = 60
HARD_MAX_CHARS = 84
HARD_MAX_WORDS = 18

# Minimum segment size — avoids per-word fragmentation
MIN_DURATION = 1.4
MIN_CHARS = 18
MIN_WORDS = 3
