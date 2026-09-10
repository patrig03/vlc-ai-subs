"""Data models for segmentation."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Word:
    """A single word with timing from Whisper."""

    text: str
    start: float
    end: float
    probability: Optional[float] = None


@dataclass
class SubtitleSegment:
    """A subtitle cue produced from a group of words."""

    words: list[Word]
    start: float
    end: float
    text: str
