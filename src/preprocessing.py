"""Offset-preserving preprocessing views for clinical text.

All public spans in this module use Python's half-open convention ``[start, end)``
and are anchored to the original, immutable raw string. Normalized text is only a
lookup view; callers must map matches back to raw text before emitting entities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from src.normalization import normalize_with_mapping
from src.offset_mapper import OffsetMapper


_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?:[.!?]+(?=\s|$)|\r\n|\r|\n)")


@dataclass(frozen=True)
class TextSpan:
    """A raw-text span using half-open offsets."""

    text: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"Invalid half-open span [{self.start}, {self.end})")


@dataclass(frozen=True)
class TextWindow(TextSpan):
    """A line, sentence, or model window anchored to raw text."""

    window_id: int
    kind: str


@dataclass(frozen=True)
class TokenOffset(TextSpan):
    """A lightweight raw token with optional coordinates in the lookup view."""

    token_id: int
    normalized_start: Optional[int] = None
    normalized_end: Optional[int] = None


@dataclass
class PreprocessedText:
    """Parallel raw and lookup views plus offset-preserving structural views."""

    raw_text: str
    normalized_lookup_text: str
    norm_to_raw_map: List[int]
    raw_to_norm_map: List[int]
    line_windows: List[TextWindow] = field(default_factory=list)
    sentence_windows: List[TextWindow] = field(default_factory=list)
    model_windows: List[TextWindow] = field(default_factory=list)
    token_offsets: List[TokenOffset] = field(default_factory=list)

    def create_offset_mapper(self) -> OffsetMapper:
        """Create a mapper backed by the exact maps used by this view."""
        return OffsetMapper(
            raw_text=self.raw_text,
            normalized_text=self.normalized_lookup_text,
            norm_to_raw_map=self.norm_to_raw_map,
            raw_to_norm_map=self.raw_to_norm_map,
        )

    def validate(self) -> None:
        """Raise ``ValueError`` if any generated view violates raw offsets."""
        if len(self.norm_to_raw_map) != len(self.normalized_lookup_text):
            raise ValueError("norm_to_raw_map length does not match normalized text")
        if len(self.raw_to_norm_map) != len(self.raw_text):
            raise ValueError("raw_to_norm_map length does not match raw text")

        for span in [*self.line_windows, *self.sentence_windows, *self.model_windows, *self.token_offsets]:
            if span.end > len(self.raw_text):
                raise ValueError(f"Span exceeds raw text: {span}")
            if self.raw_text[span.start:span.end] != span.text:
                raise ValueError(f"Raw round-trip failed for span: {span}")


def _trim_raw_span(raw_text: str, start: int, end: int) -> Optional[Tuple[int, int]]:
    """Trim surrounding whitespace without modifying text inside a span."""
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def build_line_windows(raw_text: str, include_empty: bool = True) -> List[TextWindow]:
    """Split physical lines while retaining exact raw coordinates and CR/LF style."""
    windows: List[TextWindow] = []
    line_start = 0

    for match in re.finditer(r"\r\n|\r|\n", raw_text):
        line_end = match.start()
        if include_empty or line_end > line_start:
            windows.append(
                TextWindow(
                    text=raw_text[line_start:line_end],
                    start=line_start,
                    end=line_end,
                    window_id=len(windows),
                    kind="line",
                )
            )
        line_start = match.end()

    if include_empty or line_start < len(raw_text):
        windows.append(
            TextWindow(
                text=raw_text[line_start:],
                start=line_start,
                end=len(raw_text),
                window_id=len(windows),
                kind="line",
            )
        )
    return windows


def build_sentence_windows(raw_text: str) -> List[TextWindow]:
    """Create conservative sentence-like spans using punctuation and newlines."""
    windows: List[TextWindow] = []
    segment_start = 0

    for match in _SENTENCE_BOUNDARY_PATTERN.finditer(raw_text):
        boundary_end = match.start() if match.group(0) in {"\r", "\n", "\r\n"} else match.end()
        trimmed = _trim_raw_span(raw_text, segment_start, boundary_end)
        if trimmed is not None:
            start, end = trimmed
            windows.append(TextWindow(raw_text[start:end], start, end, len(windows), "sentence"))
        segment_start = match.end()

    trimmed = _trim_raw_span(raw_text, segment_start, len(raw_text))
    if trimmed is not None:
        start, end = trimmed
        windows.append(TextWindow(raw_text[start:end], start, end, len(windows), "sentence"))
    return windows


def _choose_window_end(raw_text: str, start: int, hard_end: int) -> int:
    """Prefer a nearby whitespace/punctuation boundary over a hard character cut."""
    if hard_end >= len(raw_text):
        return len(raw_text)
    minimum_soft_end = start + max(1, (hard_end - start) // 2)
    for index in range(hard_end, minimum_soft_end, -1):
        if raw_text[index - 1].isspace() or raw_text[index - 1] in ".!?;,:)]}":
            return index
    return hard_end


def build_model_windows(raw_text: str, max_chars: int = 512, overlap_chars: int = 64) -> List[TextWindow]:
    """Build overlapping raw windows for encoders without losing document offsets."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must satisfy 0 <= overlap_chars < max_chars")
    if not raw_text:
        return []

    windows: List[TextWindow] = []
    start = 0
    while start < len(raw_text):
        hard_end = min(len(raw_text), start + max_chars)
        end = _choose_window_end(raw_text, start, hard_end)
        if end <= start:
            end = hard_end
        windows.append(TextWindow(raw_text[start:end], start, end, len(windows), "model"))
        if end >= len(raw_text):
            break

        next_start = max(start + 1, end - overlap_chars)
        while next_start < end and next_start > start and not raw_text[next_start - 1].isspace():
            next_start -= 1
        start = next_start if next_start > start else end

    return windows


def _normalized_bounds_for_raw_span(raw_to_norm_map: Sequence[int], start: int, end: int) -> Tuple[Optional[int], Optional[int]]:
    mapped = [index for index in raw_to_norm_map[start:end] if index >= 0]
    if not mapped:
        return None, None
    return min(mapped), max(mapped) + 1


def build_token_offsets(raw_text: str, raw_to_norm_map: Sequence[int]) -> List[TokenOffset]:
    """Tokenize words and punctuation while keeping raw and lookup coordinates."""
    tokens: List[TokenOffset] = []
    for match in _TOKEN_PATTERN.finditer(raw_text):
        start, end = match.span()
        normalized_start, normalized_end = _normalized_bounds_for_raw_span(raw_to_norm_map, start, end)
        tokens.append(
            TokenOffset(
                text=match.group(0),
                start=start,
                end=end,
                token_id=len(tokens),
                normalized_start=normalized_start,
                normalized_end=normalized_end,
            )
        )
    return tokens


def preprocess_text(raw_text: str, max_window_chars: int = 512, overlap_chars: int = 64) -> PreprocessedText:
    """Build all offset-preserving preprocessing representations for one note."""
    normalized, norm_to_raw, raw_to_norm = normalize_with_mapping(raw_text, for_matching=True)
    result = PreprocessedText(
        raw_text=raw_text,
        normalized_lookup_text=normalized,
        norm_to_raw_map=norm_to_raw,
        raw_to_norm_map=raw_to_norm,
        line_windows=build_line_windows(raw_text),
        sentence_windows=build_sentence_windows(raw_text),
        model_windows=build_model_windows(raw_text, max_window_chars, overlap_chars),
        token_offsets=build_token_offsets(raw_text, raw_to_norm),
    )
    result.validate()
    return result
