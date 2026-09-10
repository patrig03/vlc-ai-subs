#!/usr/bin/env python3
"""
vlc-ai-subs — Whisper transcription backend.

Transcribes audio from a media file using faster-whisper (or openai-whisper
as fallback) and streams results as JSON lines to stdout. Also writes a
standard SRT subtitle file next to the source media.

Usage:
    python3 aisubs.py <media_path> <model> <language> <task> [out_file] [audio_track] [audio_channel]

Arguments:
    media_path    Path to the video/audio file
    model         Whisper model size: tiny, base, small, medium, large
    language      Language code (e.g. en, es, hi) or "auto" for detection
    task          "transcribe" or "translate" (translate outputs English)
    out_file      Optional path to also write JSON lines (used by VLC Lua plugin)
    audio_track   Audio track index: "auto" (default, first track) or 0,1,2...
                  Maps to ffmpeg 0:a:<N>. Uses ffprobe stream index.
    audio_channel Audio channel selection within the track:
                  "auto" (default, mix to mono), "mono"/"mix", "left", "right",
                  "center" or numeric channel index 0,1,2...

Output (stdout):
    One JSON object per line:
      {"type": "status", "msg": "..."}           — progress updates
      {"type": "sub", "i": N, "start": S, "end": E, "text": "..."}  — subtitle
      {"type": "done", "segments": N, "srt_path": "..."}            — finished
      {"type": "error", "msg": "..."}            — fatal error
"""

import sys
import os
import json
import tempfile
import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional


def format_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Subtitle segmentation logic (from boundaries.py)
# ---------------------------------------------------------------------------

@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: Optional[float] = None


@dataclass
class SubtitleSegment:
    words: list[Word]
    start: float
    end: float
    text: str


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
        chars = sum(len(w.text) + 1 for w in words[start_idx:i+1])
        word_count = i - start_idx + 1
        
        if duration > hard_max_duration or chars > hard_max_chars or word_count > hard_max_words:
            break
        candidates.append(i)
    
    if not candidates:
        return start_idx

    for i in candidates:
        duration = words[i].end - start_time
        chars = sum(len(w.text) + 1 for w in words[start_idx:i+1])
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
    chars_best = sum(len(w.text) + 1 for w in words[start_idx:best_idx+1])
    wc_best = best_idx - start_idx + 1
    p_best = punctuation_score(words[best_idx])
    if best_score < 1.0 and p_best < 8:
        # Find candidate closest to target that satisfies minima
        closest = None
        closest_score = float("-inf")
        for i in candidates:
            dur = words[i].end - start_time
            ch = sum(len(w.text) + 1 for w in words[start_idx:i+1])
            wc = i - start_idx + 1
            if dur < MIN_DURATION or ch < MIN_CHARS or wc < MIN_WORDS:
                continue
            if dur > SOFT_MAX_DURATION or ch > SOFT_MAX_CHARS:
                continue
            proximity = -abs(dur - TARGET_DURATION) * 0.5 - abs(ch - TARGET_CHARS) * 0.05
            prox_score = proximity + boundary_score(words[i], words[i+1]) * 0.3
            if prox_score > closest_score:
                closest_score = prox_score
                closest = i
        if closest is not None:
            best_idx = closest

    return best_idx


def segment_words(words: list[Word]) -> list[SubtitleSegment]:
    if not words:
        return []
    
    segments = []
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
                segments.append(SubtitleSegment(
                    words=seg_words,
                    start=seg_words[0].start,
                    end=seg_words[-1].end,
                    text=text
                ))
                break

        end_idx = find_best_boundary(words, start_idx)
        
        seg_words = words[start_idx:end_idx + 1]
        text = " ".join(w.text for w in seg_words).strip()
        
        start = seg_words[0].start
        end = seg_words[-1].end
        
        segments.append(SubtitleSegment(
            words=seg_words,
            start=start,
            end=end,
            text=text
        ))
        
        start_idx = end_idx + 1

    # Post-process: merge tiny segments (avoids 1-2 word fragments like "punctuation,")
    # First handle tail, then any middle singletons
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
                    text=merged_text
                )
                segments.pop()

    # Merge any remaining tiny middle segments (e.g. isolated "punctuation," )
    merged: list[SubtitleSegment] = []
    for seg in segments:
        if merged and len(seg.words) < MIN_WORDS:
            # Don't isolate weak punctuation alone; merge with previous if possible
            # Keep single-word sentence ends like "Yes." alone, but merge weak punctuation
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
                        text=" ".join(w.text for w in combined_words).strip()
                    )
                    continue
        # Also check if previous is tiny and should be merged forward
        if merged and len(merged[-1].words) < MIN_WORDS and not ends_sentence(merged[-1].words[-1].text):
            prev = merged.pop()
            combined_words = prev.words + seg.words
            combined_chars = sum(len(w.text) + 1 for w in combined_words)
            combined_dur = combined_words[-1].end - combined_words[0].start
            if combined_dur <= HARD_MAX_DURATION and combined_chars <= HARD_MAX_CHARS and len(combined_words) <= HARD_MAX_WORDS:
                merged.append(SubtitleSegment(
                    words=combined_words,
                    start=combined_words[0].start,
                    end=combined_words[-1].end,
                    text=" ".join(w.text for w in combined_words).strip()
                ))
                continue
            else:
                merged.append(prev)
        merged.append(seg)

    return merged


def break_lines(text: str, max_chars: int = TARGET_CHARS) -> str:
    words = text.split()
    if not words:
        return text
    
    if len(text) <= max_chars:
        return text
    
    lines = []
    current_line = []
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


def refine_timing(segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
    refined = []
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
        
        refined.append(SubtitleSegment(
            words=seg.words,
            start=max(0.0, start),
            end=max(start + 0.1, end),
            text=seg.text
        ))
    
    return refined


def words_from_whisper(whisper_words) -> list[Word]:
    words = []
    for w in whisper_words:
        if w.start is not None and w.end is not None:
            words.append(Word(
                text=w.word,
                start=w.start,
                end=w.end,
                probability=getattr(w, "probability", None)
            ))
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

# Try to keep boundaries.py as canonical source if available — re-export its
# symbols to stay in sync when the file is updated. If import fails we already
# have the inline definitions above.
try:
    import boundaries as _boundaries  # type: ignore
    # Overwrite inline definitions with the canonical ones when available
    Word = _boundaries.Word  # type: ignore
    SubtitleSegment = _boundaries.SubtitleSegment  # type: ignore
    TARGET_DURATION = _boundaries.TARGET_DURATION  # type: ignore
    SOFT_MAX_DURATION = _boundaries.SOFT_MAX_DURATION  # type: ignore
    HARD_MAX_DURATION = _boundaries.HARD_MAX_DURATION  # type: ignore
    TARGET_CHARS = _boundaries.TARGET_CHARS  # type: ignore
    SOFT_MAX_CHARS = _boundaries.SOFT_MAX_CHARS  # type: ignore
    HARD_MAX_CHARS = _boundaries.HARD_MAX_CHARS  # type: ignore
    HARD_MAX_WORDS = _boundaries.HARD_MAX_WORDS  # type: ignore
    ends_sentence = _boundaries.ends_sentence  # type: ignore
    ends_clause = _boundaries.ends_clause  # type: ignore
    ends_weak_punct = _boundaries.ends_weak_punct  # type: ignore
    silence_score = _boundaries.silence_score  # type: ignore
    punctuation_score = _boundaries.punctuation_score  # type: ignore
    boundary_score = _boundaries.boundary_score  # type: ignore
    duration_penalty = _boundaries.duration_penalty  # type: ignore
    length_penalty = _boundaries.length_penalty  # type: ignore
    find_best_boundary = _boundaries.find_best_boundary  # type: ignore
    segment_words = _boundaries.segment_words  # type: ignore
    break_lines = _boundaries.break_lines  # type: ignore
    refine_timing = _boundaries.refine_timing  # type: ignore
    words_from_whisper = _boundaries.words_from_whisper  # type: ignore
    process_whisper_segment = _boundaries.process_whisper_segment  # type: ignore
except ImportError:
    pass


_out_file = None  # optional output file set in main()

def emit(data: dict) -> None:
    """Write a JSON line to stdout and to the output file if set."""
    line = json.dumps(data, ensure_ascii=False)
    print(line, flush=True)
    if _out_file:
        try:
            _out_file.write(line + "\n")
            _out_file.flush()
        except Exception:
            pass


def prepare_audio_source(media_path, audio_track, audio_channel):
    """
    Prepare an audio file for Whisper based on track/channel selection.

    If audio_track is 'auto' and audio_channel is 'auto'/'mix', return the
    original media_path (Whisper/ffmpeg will handle decoding).

    Otherwise use ffmpeg to extract the requested track/channel to a temp
    16 kHz mono WAV which is optimal for Whisper.

    Returns (path_to_use, temp_path_to_cleanup or None).
    """
    track = (audio_track or "auto").strip().lower()
    channel = (audio_channel or "auto").strip().lower()

    # Normalise channel aliases
    if channel in ("", "auto", "default"):
        channel = "auto"
    elif channel in ("mono", "mix", "mixed", "downmix"):
        channel = "mono"
    elif channel in ("left", "l", "channel0", "ch0", "0"):
        # Distinguish numeric track vs channel — channel already normalised
        # Keep numeric channel as left/right only when explicitly channel param
        if channel == "0":
            channel = "left"
        # else left stays left
    elif channel in ("right", "r", "channel1", "ch1", "1"):
        if channel == "1":
            channel = "right"
    elif channel.isdigit():
        # Generic channel index: treat as cN
        pass

    needs_extraction = False
    if track != "auto":
        needs_extraction = True
    if channel != "auto":
        needs_extraction = True

    if not needs_extraction:
        return media_path, None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # No ffmpeg — fall back to original file with warning
        emit({"type": "status", "msg": "ffmpeg not found; using default audio (channel selection ignored)"})
        return media_path, None

    # Create temp wav next to the output or in system temp
    tmp_fd, tmp_wav = tempfile.mkstemp(suffix=".wav", prefix="aisubs_audio_")
    os.close(tmp_fd)

    cmd = [ffmpeg, "-y", "-v", "error", "-i", media_path]

    # Map specific audio track (0-based index of audio streams: 0:a:<idx>)
    if track != "auto":
        try:
            idx = int(track)
            if idx < 0:
                raise ValueError()
            cmd += ["-map", f"0:a:{idx}"]
        except ValueError:
            emit({"type": "error", "msg": f"Invalid audio track '{audio_track}': must be 'auto' or 0,1,2..."})
            try:
                os.remove(tmp_wav)
            except Exception:
                pass
            sys.exit(1)
    # If a channel filter is requested but no explicit track map, ffmpeg will
    # default to the first audio stream — which is the desired "auto" behaviour.

    # Channel extraction / downmix
    if channel == "left":
        cmd += ["-filter:a", "pan=mono|c0=c0"]
    elif channel == "right":
        cmd += ["-filter:a", "pan=mono|c0=c1"]
    elif channel == "center":
        cmd += ["-filter:a", "pan=mono|c0=c2"]
    elif channel.isdigit():
        # Generic channel N -> pan mono from that channel
        cmd += ["-filter:a", f"pan=mono|c0=c{channel}"]
    elif channel == "mono":
        # Explicit mono downmix — ffmpeg does this by default with -ac 1
        pass
    # "auto" -> no filter, keep original channel layout until -ac 1 below

    # Always convert to 16 kHz mono PCM for Whisper
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", tmp_wav]

    emit({"type": "status", "msg": f"Extracting audio track={track} channel={channel} via ffmpeg..."})
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        emit({"type": "error", "msg": "ffmpeg audio extraction timed out"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        emit({"type": "error", "msg": f"Failed to run ffmpeg: {e}"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        emit({"type": "error", "msg": f"ffmpeg failed (track={track} channel={channel}): {err or 'unknown error'}"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)

    if not os.path.isfile(tmp_wav) or os.path.getsize(tmp_wav) == 0:
        emit({"type": "error", "msg": f"ffmpeg produced no output for track={track} channel={channel}"})
        try:
            os.remove(tmp_wav)
        except Exception:
            pass
        sys.exit(1)

    emit({"type": "status", "msg": f"Audio extracted to temp WAV (track={track} channel={channel})"})
    return tmp_wav, tmp_wav


def transcribe_whisper(media_path, model_name, lang, task):
    """Transcribe using faster-whisper (CTranslate2 backend)."""
    from faster_whisper import WhisperModel

    emit({
        "type": "status", 
        "msg": f"Loading {model_name} model..."
    })

    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

    emit({
        "type": "status", 
        "msg": "Transcribing..."
    })

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


def _emit_segment(start: float, end: float, text: str, count: int, srt_lines: list):
    """Helper to emit a single subtitle segment and append to SRT lines."""
    text = break_lines(text.strip())
    # Ensure sane timing
    start = max(0.0, start)
    end = max(start + 0.1, end)
    emit({
        "type": "sub",
        "i": count,
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
    })
    srt_lines.append(
        f"{count}\n"
        f"{format_srt_timestamp(start)} --> "
        f"{format_srt_timestamp(end)}\n"
        f"{text}\n"
    )


def main():
    global _out_file

    if len(sys.argv) < 5:
        emit({
            "type": "error", 
            "msg": "Usage: aisubs.py <media> <model> <lang> <task> [out_file]"
        })
        sys.exit(1)

    media_path = sys.argv[1]
    model_name = sys.argv[2]
    language = sys.argv[3] if sys.argv[3] != "auto" else None
    task = sys.argv[4]

    # Optional output file — Lua passes this so output is captured without shell redirection
    # Arg layout: <media> <model> <lang> <task> [out_file] [audio_track] [audio_channel]
    # audio_track: "auto" or 0,1,2... (index among audio streams, 0:a:N)
    # audio_channel: "auto"/"mono"/"left"/"right"/"center" or numeric channel index
    out_file_arg = None
    audio_track = "auto"
    audio_channel = "auto"
    if len(sys.argv) > 5:
        out_file_arg = sys.argv[5]
        try:
            _out_file = open(
                out_file_arg,
                "w",
                encoding="utf-8",
                buffering=1
            )
        except Exception as e:
            pass  # if we can't open it, stdout-only mode
    if len(sys.argv) > 6:
        audio_track = sys.argv[6] or "auto"
    if len(sys.argv) > 7:
        audio_channel = sys.argv[7] or "auto"
    # Handle legacy duplicate tmp_file passed as 6th arg (when Lua passed tmp twice)
    # If audio_track looks like a temp file path, treat as not set
    if audio_track and ("/aisubs_" in audio_track or "\\aisubs_" in audio_track or audio_track.endswith(".txt")):
        audio_track = "auto"
        audio_channel = "auto"

    if not os.path.isfile(media_path):
        emit({
            "type": "error",
            "msg": f"File not found: {media_path}"
        })
        sys.exit(1)

    try:
        import faster_whisper
    except ImportError:
        emit({
            "type": "error",
            "msg": "No Whisper backend found. Run: pip install faster-whisper"
        })
        sys.exit(1)

    # Prepare audio source (ffmpeg extraction if track/channel selection requested)
    transcribe_path = media_path
    temp_audio = None
    try:
        transcribe_path, temp_audio = prepare_audio_source(media_path, audio_track, audio_channel)
    except SystemExit:
        raise
    except Exception as e:
        emit({"type": "error", "msg": f"Audio preparation failed: {e}"})
        sys.exit(1)

    srt_lines = []
    count = 0

    try:
        for seg in transcribe_whisper(transcribe_path, model_name, language, task):
            text = seg["text"]
            words = seg["words"]

            # --- New segmentation logic ---
            # Use word-level boundaries when word timestamps are available.
            segmented = False
            if words:
                # Filter words with valid timestamps via boundaries helper
                try:
                    our_words = words_from_whisper(words)
                except Exception:
                    our_words = []

                if our_words:
                    try:
                        sub_segments = segment_words(our_words)
                        sub_segments = refine_timing(sub_segments)
                    except Exception:
                        sub_segments = []

                    if sub_segments:
                        for sub in sub_segments:
                            seg_text = break_lines(sub.text)
                            seg_start = sub.start
                            seg_end = sub.end
                            count += 1
                            emit({
                                "type": "sub",
                                "i": count,
                                "start": round(max(0.0, seg_start), 3),
                                "end": round(max(seg_start + 0.1, seg_end), 3),
                                "text": seg_text,
                            })
                            srt_lines.append(
                                f"{count}\n"
                                f"{format_srt_timestamp(max(0.0, seg_start))} --> "
                                f"{format_srt_timestamp(max(seg_start + 0.1, seg_end))}\n"
                                f"{seg_text}\n"
                            )
                        segmented = True
                    else:
                        # Fallback: single-word or tiny list — emit as one segment
                        # segment_words handles this but keep fallback
                        pass

            if segmented:
                continue

            # Fallback path: no usable word timestamps — use original whisper timing
            if words:
                words = [
                    w for w in words
                    if w.start is not None and w.end is not None
                ]

            if words:
                start = max(0.0, words[0].start - 0.05)
                end = words[-1].end + 0.05
            else:
                start = seg["start"]
                end = seg["end"]

            # Apply line breaking to fallback text as well
            text = break_lines(text)

            count += 1

            emit({
                "type": "sub",
                "i": count,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            })

            srt_lines.append(
                f"{count}\n"
                f"{format_srt_timestamp(start)} --> "
                f"{format_srt_timestamp(end)}\n"
                f"{text}\n"
            )

    except Exception as e:
        import traceback

        emit({
            "type": "error",
            "msg": f"Transcription failed: {e}\n{traceback.format_exc()}"
        })
        if temp_audio:
            try:
                os.remove(temp_audio)
            except Exception:
                pass
        sys.exit(1)
    finally:
        if temp_audio:
            try:
                os.remove(temp_audio)
            except Exception:
                pass

    # Write SRT file next to the media
    base, _ = os.path.splitext(media_path)
    srt_path = base + ".srt"

    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
    except Exception as e:
        emit({
            "type": "error",
            "msg": f"Could not write SRT: {e}"
        })
        sys.exit(1)

    emit({
        "type": "done",
        "segments": count,
        "srt_path": srt_path
    })

    if _out_file:
        _out_file.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        emit({
            "type": "error", 
            "msg": str(e) + "\n" + traceback.format_exc()
        })
        if _out_file:
            _out_file.close()
        sys.exit(1)
