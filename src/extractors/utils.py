from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from src.data_types import Chunk, SpanCandidate, TextViews
from src.linking.terminology_normalizer import normalize_no_diacritics_for_lookup, normalize_whitespace


_WORD_RE = re.compile(r"\w", flags=re.UNICODE)


def make_span_candidate(
    raw_text: str,
    start: int,
    end: int,
    *,
    raw_type: str | None,
    source: str,
    score: float,
    chunk: Chunk | None = None,
    features: Mapping[str, Any] | None = None,
    context_window: int = 80,
) -> SpanCandidate:
    validate_raw_span(raw_text, start, end)
    left, right = get_context(raw_text, start, end, window=context_window)
    return SpanCandidate(
        text=raw_text[start:end],
        start=start,
        end=end,
        raw_type=raw_type,
        source=source,
        score=score,
        section=chunk.section if chunk else None,
        subsection=chunk.subsection if chunk else None,
        context_left=left,
        context_right=right,
        features=dict(features or {}),
    )


def validate_raw_span(raw_text: str, start: int, end: int) -> None:
    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError("Span start/end must be integers")
    if start < 0 or end <= start or end > len(raw_text):
        raise ValueError(f"Invalid raw span ({start}, {end}) for text length {len(raw_text)}")


def get_context(raw_text: str, start: int, end: int, *, window: int = 80) -> tuple[str, str]:
    return raw_text[max(0, start - window) : start], raw_text[end : min(len(raw_text), end + window)]


def dedupe_candidates(candidates: Iterable[SpanCandidate]) -> list[SpanCandidate]:
    best: dict[tuple[int, int, str | None, str], SpanCandidate] = {}
    for cand in candidates:
        key = (cand.start, cand.end, cand.raw_type, cand.source)
        previous = best.get(key)
        if previous is None or cand.score > previous.score:
            best[key] = cand
    return sorted(best.values(), key=lambda c: (c.start, c.end, c.source, c.raw_type or ""))


def sort_longest_first(values: Iterable[str]) -> list[str]:
    unique = {normalize_whitespace(value) for value in values if normalize_whitespace(value)}
    return sorted(unique, key=lambda value: (-len(value), value.lower()))


def find_phrase_matches(
    raw_text: str,
    views: TextViews,
    phrase: str,
    *,
    chunk: Chunk | None = None,
    min_length: int = 1,
    require_boundaries: bool = True,
) -> list[tuple[int, int]]:
    """Find a phrase using the no-diacritics mapped view and return raw spans."""

    needle = normalize_no_diacritics_for_lookup(phrase)
    if len(needle) < min_length:
        return []

    view = views.no_diacritics
    view_to_raw = views.no_diacritics_to_raw
    search_start = 0
    search_end = len(view)
    if chunk is not None:
        # Convert raw chunk boundaries approximately into view boundaries.
        chunk_view_indices = [idx for idx, raw_idx in enumerate(view_to_raw) if chunk.start <= raw_idx < chunk.end]
        if not chunk_view_indices:
            return []
        search_start = chunk_view_indices[0]
        search_end = chunk_view_indices[-1] + 1

    spans: list[tuple[int, int]] = []
    cursor = search_start
    while cursor < search_end:
        found = view.find(needle, cursor, search_end)
        if found == -1:
            break
        view_end = found + len(needle)
        if not require_boundaries or _has_view_boundaries(view, found, view_end):
            raw_start = view_to_raw[found]
            raw_end = view_to_raw[view_end - 1] + 1
            if raw_start < raw_end:
                spans.append((raw_start, raw_end))
        cursor = found + 1
    return spans


def _has_view_boundaries(view: str, start: int, end: int) -> bool:
    before_ok = start == 0 or not _WORD_RE.match(view[start - 1])
    after_ok = end >= len(view) or not _WORD_RE.match(view[end])
    return before_ok and after_ok


def trim_trailing_punctuation(raw_text: str, start: int, end: int) -> tuple[int, int]:
    while end > start and raw_text[end - 1] in " ,;:.\n\t\r":
        end -= 1
    while start < end and raw_text[start] in " ,;:.\n\t\r-*•":
        start += 1
    return start, end


def span_overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)
