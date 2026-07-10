from __future__ import annotations

from src.preprocess.normalizer import build_text_views


def test_build_text_views_preserves_raw_and_maps_lengths() -> None:
    raw = "Bệnh   nhân\nHo sốt"
    views = build_text_views(raw)

    assert views.raw == raw
    assert views.normalized == "bệnh nhân ho sốt"
    assert views.search == "benh nhan ho sot"
    assert len(views.normalized) == len(views.norm_to_raw)
    assert len(views.search) == len(views.search_to_raw)
    assert len(views.no_diacritics) == len(views.no_diacritics_to_raw)


def test_no_diacritics_view_supports_vietnamese_lookup() -> None:
    raw = "Bệnh trào ngược dạ dày"
    views = build_text_views(raw)

    assert views.no_diacritics == "benh trao nguoc da day"


def test_collapsed_whitespace_maps_to_valid_raw_indices() -> None:
    raw = "A\t\tB  C"
    views = build_text_views(raw)

    assert views.normalized == "a b c"
    assert all(0 <= idx < len(raw) for idx in views.norm_to_raw)
