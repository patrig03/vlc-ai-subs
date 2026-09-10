"""Subtitle segmentation algorithm.

Groups word-level timestamps into readable subtitle cues
by scoring candidate boundaries on punctuation, silence gaps,
duration and character length.
"""

from .constants import (
    HARD_MAX_CHARS,
    HARD_MAX_DURATION,
    HARD_MAX_WORDS,
    MIN_CHARS,
    MIN_DURATION,
    MIN_WORDS,
    SOFT_MAX_CHARS,
    SOFT_MAX_DURATION,
    TARGET_CHARS,
    TARGET_DURATION,
)
from .formatting import break_lines
from .models import SubtitleSegment, Word
from .scoring import (
    boundary_score,
    duration_penalty,
    ends_sentence,
    length_penalty,
    punctuation_score,
    silence_score,
)


def find_best_boundary(
    words: list[Word],
    start_idx: int,
    hard_max_duration: float = HARD_MAX_DURATION,
    hard_max_chars: int = HARD_MAX_CHARS,
    hard_max_words: int = HARD_MAX_WORDS,
) -> int:
    best_idx = start_idx
    best_score = float("-inf")
    start_time = words[start_idx].start

    # Collect candidates within hard limits
    candidates: list[int] = []
    for i in range(start_idx, len(words) - 1):
        duration = words[i].end - start_time
        chars = sum(len(w.text) + 1 for w in words[start_idx : i + 1])
        word_count = i - start_idx + 1

        if duration > hard_max_duration or chars > hard_max_chars or word_count > hard_max_words:
            break
        candidates.append(i)

    if not candidates:
        return start_idx

    for i in candidates:
        duration = words[i].end - start_time
        chars = sum(len(w.text) + 1 for w in words[start_idx : i + 1])
        word_count = i - start_idx + 1

        score = boundary_score(words[i], words[i + 1])
        score -= duration_penalty(duration)
        score -= length_penalty(chars)

        # Discourage very short segments unless there's a strong cue
        p_score = punctuation_score(words[i])
        s_score = silence_score(words[i + 1].start - words[i].end)
        is_strong = p_score >= 8 or s_score >= 5

        if not is_strong:
            if duration < MIN_DURATION:
                score -= (MIN_DURATION - duration) * 1.5
            if chars < MIN_CHARS:
                score -= (MIN_CHARS - chars) * 0.1
            if word_count < MIN_WORDS:
                score -= (MIN_WORDS - word_count) * 1.0
            # Avoid creating a tiny tail
            remaining = len(words) - (i + 1)
            if 0 < remaining < MIN_WORDS:
                score -= (MIN_WORDS - remaining) * 2.0
        else:
            # Strong cue: small bonus for filling towards target
            if duration < TARGET_DURATION:
                score += min(duration / TARGET_DURATION, 1.0) * 0.3

        # Small packing bonus when still within target — prefer longer when scores tie
        if duration <= TARGET_DURATION and chars <= TARGET_CHARS:
            score += (duration / TARGET_DURATION) * 0.15
            score += (chars / TARGET_CHARS) * 0.15

        # Use >= so that when scores tie we prefer the longer (target-filling) candidate
        if score >= best_score:
            best_score = score
            best_idx = i

    # If no strong cue was found (best_score low) and best is still very short,
    # extend to the best target-filling candidate
    duration_best = words[best_idx].end - start_time
    chars_best = sum(len(w.text) + 1 for w in words[start_idx : best_idx + 1])
    p_best = punctuation_score(words[best_idx])
    if best_score < 1.0 and p_best < 8:
        closest = None
        closest_score = float("-inf")
        for i in candidates:
            dur = words[i].end - start_time
            ch = sum(len(w.text) + 1 for w in words[start_idx : i + 1])
            wc = i - start_idx + 1
            if dur < MIN_DURATION or ch < MIN_CHARS or wc < MIN_WORDS:
                continue
            if dur > SOFT_MAX_DURATION or ch > SOFT_MAX_CHARS:
                continue
            proximity = -abs(dur - TARGET_DURATION) * 0.5 - abs(ch - TARGET_CHARS) * 0.05
            prox_score = proximity + boundary_score(words[i], words[i + 1]) * 0.3
            if prox_score > closest_score:
                closest_score = prox_score
                closest = i
        if closest is not None:
            best_idx = closest

    return best_idx


def segment_words(words: list[Word]) -> list[SubtitleSegment]:
    if not words:
        return []

    segments: list[SubtitleSegment] = []
    start_idx = 0

    while start_idx < len(words):
        # If the remainder fits comfortably in one segment, keep it together
        remaining = len(words) - start_idx
        if remaining <= 6:
            dur = words[-1].end - words[start_idx].start
            chars = sum(len(w.text) + 1 for w in words[start_idx:])
            if dur <= TARGET_DURATION + 1.0 and chars <= SOFT_MAX_CHARS and remaining <= HARD_MAX_WORDS:
                seg_words = words[start_idx:]
                text = " ".join(w.text for w in seg_words).strip()
                segments.append(
                    SubtitleSegment(
                        words=seg_words,
                        start=seg_words[0].start,
                        end=seg_words[-1].end,
                        text=text,
                    )
                )
                break

        end_idx = find_best_boundary(words, start_idx)

        seg_words = words[start_idx : end_idx + 1]
        text = " ".join(w.text for w in seg_words).strip()

        start = seg_words[0].start
        end = seg_words[-1].end

        segments.append(SubtitleSegment(words=seg_words, start=start, end=end, text=text))

        start_idx = end_idx + 1

    # Post-process: merge tiny segments (avoids 1-2 word fragments like "punctuation,")
    if len(segments) >= 2:
        last = segments[-1]
        if len(last.words) < MIN_WORDS and len(last.text) < MIN_CHARS:
            prev = segments[-2]
            merged_words = prev.words + last.words
            merged_chars = sum(len(w.text) + 1 for w in merged_words)
            merged_dur = merged_words[-1].end - merged_words[0].start
            if merged_dur <= HARD_MAX_DURATION and merged_chars <= HARD_MAX_CHARS and len(merged_words) <= HARD_MAX_WORDS:
                merged_text = " ".join(w.text for w in merged_words).strip()
                segments[-2] = SubtitleSegment(
                    words=merged_words,
                    start=merged_words[0].start,
                    end=merged_words[-1].end,
                    text=merged_text,
                )
                segments.pop()

    # Merge any remaining tiny middle segments (e.g. isolated "punctuation," )
    merged: list[SubtitleSegment] = []
    for seg in segments:
        if merged and len(seg.words) < MIN_WORDS:
            # Don't isolate weak punctuation alone; merge with previous if possible
            is_sentence_end = ends_sentence(seg.words[-1].text)
            if not is_sentence_end:
                prev = merged[-1]
                combined_words = prev.words + seg.words
                combined_chars = sum(len(w.text) + 1 for w in combined_words)
                combined_dur = combined_words[-1].end - combined_words[0].start
                if combined_dur <= HARD_MAX_DURATION and combined_chars <= HARD_MAX_CHARS and len(combined_words) <= HARD_MAX_WORDS:
                    merged[-1] = SubtitleSegment(
                        words=combined_words,
                        start=combined_words[0].start,
                        end=combined_words[-1].end,
                        text=" ".join(w.text for w in combined_words).strip(),
                    )
                    continue
        # Also check if previous is tiny and should be merged forward
        if merged and len(merged[-1].words) < MIN_WORDS and not ends_sentence(merged[-1].words[-1].text):
            prev = merged.pop()
            combined_words = prev.words + seg.words
            combined_chars = sum(len(w.text) + 1 for w in combined_words)
            combined_dur = combined_words[-1].end - combined_words[0].start
            if combined_dur <= HARD_MAX_DURATION and combined_chars <= HARD_MAX_CHARS and len(combined_words) <= HARD_MAX_WORDS:
                merged.append(
                    SubtitleSegment(
                        words=combined_words,
                        start=combined_words[0].start,
                        end=combined_words[-1].end,
                        text=" ".join(w.text for w in combined_words).strip(),
                    )
                )
                continue
            else:
                merged.append(prev)
        merged.append(seg)

    return merged


def refine_timing(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    refined: list[SubtitleSegment] = []
    for i, seg in enumerate(segments):
        start = seg.start
        end = seg.end

        if i > 0:
            prev_end = refined[-1].end
            gap = start - prev_end
            if gap > 0.1:
                start = prev_end + gap * 0.5

        if i < len(segments) - 1:
            next_start = segments[i + 1].start
            gap = next_start - end
            if gap > 0.1:
                end = next_start - gap * 0.5

        refined.append(
            SubtitleSegment(
                words=seg.words,
                start=max(0.0, start),
                end=max(start + 0.1, end),
                text=seg.text,
            )
        )

    return refined


def words_from_whisper(whisper_words) -> list[Word]:
    words: list[Word] = []
    for w in whisper_words:
        if w.start is not None and w.end is not None:
            words.append(
                Word(
                    text=w.word,
                    start=w.start,
                    end=w.end,
                    probability=getattr(w, "probability", None),
                )
            )
    return words


def process_whisper_segment(whisper_segment) -> list[SubtitleSegment]:
    words = words_from_whisper(whisper_segment.words)
    if not words:
        return []

    segments = segment_words(words)
    segments = refine_timing(segments)

    for seg in segments:
        seg.text = break_lines(seg.text)

    return segments
