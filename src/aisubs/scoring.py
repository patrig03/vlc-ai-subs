"""Scoring helpers for subtitle boundary selection."""

from .constants import (
    CLAUSE_PUNCT,
    SENTENCE_END_PUNCT,
    WEAK_PUNCT,
    HARD_MAX_DURATION,
    TARGET_DURATION,
    SOFT_MAX_DURATION,
    TARGET_CHARS,
    SOFT_MAX_CHARS,
)
from .models import Word


def ends_sentence(text: str) -> bool:
    t = text.strip()
    return bool(t) and t[-1] in SENTENCE_END_PUNCT


def ends_clause(text: str) -> bool:
    t = text.strip()
    return bool(t) and t[-1] in CLAUSE_PUNCT


def ends_weak_punct(text: str) -> bool:
    t = text.strip()
    return bool(t) and t[-1] in WEAK_PUNCT


def silence_score(gap: float) -> float:
    if gap < 0.15:
        return 0
    if gap < 0.30:
        return 1
    if gap < 0.50:
        return 3
    if gap < 0.70:
        return 5
    if gap < 1.0:
        return 7
    return 10


def punctuation_score(left_word: Word) -> float:
    text = left_word.text.strip()
    if not text:
        return 0
    last_char = text[-1]
    if last_char in SENTENCE_END_PUNCT:
        return 12
    if last_char in CLAUSE_PUNCT:
        return 8
    if last_char in WEAK_PUNCT:
        return 3
    return 0


def boundary_score(left: Word, right: Word) -> float:
    gap = right.start - left.end
    score = 0.0
    score += punctuation_score(left)
    score += silence_score(gap)
    # Use tighter threshold to avoid penalising normal 0.1s gaps due to float error
    if gap < 0.08:
        score -= 1.5
    return score


def duration_penalty(duration: float) -> float:
    if duration <= TARGET_DURATION:
        return 0
    if duration <= SOFT_MAX_DURATION:
        return (duration - TARGET_DURATION) * 1.0
    return 2 + (duration - SOFT_MAX_DURATION) * 3


def length_penalty(chars: int) -> float:
    if chars <= TARGET_CHARS:
        return 0
    if chars <= SOFT_MAX_CHARS:
        return (chars - TARGET_CHARS) * 0.3
    return 5.4 + (chars - SOFT_MAX_CHARS) * 1.5
