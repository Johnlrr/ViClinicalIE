from __future__ import annotations


def map_view_span_to_raw(view_to_raw: list[int], start: int, end: int) -> tuple[int, int]:
    """Map a span in a normalized/search view back to raw `[start, end)` offsets."""

    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError("start and end must be integers")
    if start < 0 or end < 0 or start >= end:
        raise ValueError(f"Invalid non-empty span: ({start}, {end})")
    if end > len(view_to_raw):
        raise ValueError(f"Span end {end} exceeds view map length {len(view_to_raw)}")
    raw_start = view_to_raw[start]
    raw_end = view_to_raw[end - 1] + 1
    if raw_start >= raw_end:
        raise ValueError(f"Mapped raw span is invalid: ({raw_start}, {raw_end})")
    return raw_start, raw_end


def safe_slice(raw_text: str, start: int, end: int) -> str:
    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError("start and end must be integers")
    if start < 0 or end < start or end > len(raw_text):
        raise ValueError(f"Invalid raw slice bounds: ({start}, {end}) for text length {len(raw_text)}")
    return raw_text[start:end]


def assert_raw_span(raw_text: str, start: int, end: int, expected_text: str) -> None:
    actual = safe_slice(raw_text, start, end)
    if actual != expected_text:
        raise ValueError(
            "Raw span mismatch: "
            f"expected={expected_text!r}, actual={actual!r}, position=({start}, {end})"
        )


def repair_span_to_raw_text(
    raw_text: str,
    approx_start: int,
    approx_end: int,
    text: str,
    *,
    window: int = 5,
) -> tuple[int, int] | None:
    """Repair a near-miss span only if the expected text is unique nearby."""

    if not text:
        return None
    search_start = max(0, approx_start - window)
    search_end = min(len(raw_text), approx_end + window)
    local = raw_text[search_start:search_end]
    matches: list[tuple[int, int]] = []
    cursor = 0
    while True:
        found = local.find(text, cursor)
        if found == -1:
            break
        raw_start = search_start + found
        matches.append((raw_start, raw_start + len(text)))
        cursor = found + 1
    if len(matches) == 1:
        return matches[0]
    return None
