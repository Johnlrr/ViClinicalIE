from __future__ import annotations

import pytest

from src.preprocess.normalizer import build_text_views
from src.preprocess.offset_mapper import assert_raw_span, map_view_span_to_raw, repair_span_to_raw_text, safe_slice


def test_map_view_span_to_raw_handles_collapsed_space() -> None:
    raw = "Bệnh   nhân ho"
    views = build_text_views(raw)
    start = views.normalized.index("nhân")
    end = start + len("nhân")

    raw_start, raw_end = map_view_span_to_raw(views.norm_to_raw, start, end)
    assert raw[raw_start:raw_end] == "nhân"


def test_invalid_view_span_raises() -> None:
    with pytest.raises(ValueError):
        map_view_span_to_raw([0, 1], 1, 1)


def test_safe_slice_and_assert_raw_span() -> None:
    raw = "abc def"
    assert safe_slice(raw, 4, 7) == "def"
    assert_raw_span(raw, 4, 7, "def")


def test_repair_span_to_raw_text_nearby_unique() -> None:
    raw = "abc ho sốt xyz"
    assert repair_span_to_raw_text(raw, 3, 8, "ho sốt", window=3) == (4, 10)
    assert repair_span_to_raw_text(raw, 0, 3, "missing", window=3) is None
