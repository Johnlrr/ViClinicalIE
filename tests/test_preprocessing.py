"""Tests for offset-preserving preprocessing views."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.offset_mapper import OffsetMapper
from src.preprocessing import (
    build_line_windows,
    build_model_windows,
    build_sentence_windows,
    preprocess_text,
)


def test_preprocess_exposes_raw_safe_views():
    raw_text = "  BỆNH nhân\tđau bụng.\r\nWBC: 14,43\n- aspirin 81 mg po daily  "

    views = preprocess_text(raw_text, max_window_chars=32, overlap_chars=6)

    assert views.raw_text == raw_text
    assert views.normalized_lookup_text == "bệnh nhân đau bụng. wbc: 14,43 - aspirin 81 mg po daily"
    assert len(views.norm_to_raw_map) == len(views.normalized_lookup_text)
    assert len(views.raw_to_norm_map) == len(raw_text)
    assert views.line_windows[0].text == "  BỆNH nhân\tđau bụng."
    assert views.line_windows[0].start == 0
    assert views.line_windows[0].end == len("  BỆNH nhân\tđau bụng.")
    assert views.line_windows[1].text == "WBC: 14,43"
    assert views.line_windows[2].text == "- aspirin 81 mg po daily  "

    for span in [
        *views.line_windows,
        *views.sentence_windows,
        *views.model_windows,
        *views.token_offsets,
    ]:
        assert raw_text[span.start:span.end] == span.text


def test_normalized_match_recovers_whitespace_and_typo_spans():
    raw_text = "  cảm giác  khó chịu; atenololtrong ngày  "
    views = preprocess_text(raw_text)
    mapper = views.create_offset_mapper()

    first_start = views.normalized_lookup_text.index("cảm giác khó chịu")
    first_end = first_start + len("cảm giác khó chịu")
    first_span = mapper.recover_raw_span_from_normalized_match(first_start, first_end)
    assert first_span is not None
    assert raw_text[first_span[0]:first_span[1]] == "cảm giác  khó chịu"

    typo_start = views.normalized_lookup_text.index("atenolol trong")
    typo_end = typo_start + len("atenolol trong")
    typo_span = mapper.recover_raw_span_from_normalized_match(typo_start, typo_end)
    assert typo_span is not None
    assert raw_text[typo_span[0]:typo_span[1]] == "atenololtrong"


def test_decomposed_unicode_maps_back_to_all_raw_codepoints():
    raw_text = "e\u0301 đau"
    views = preprocess_text(raw_text)
    mapper = OffsetMapper(
        raw_text,
        views.normalized_lookup_text,
        views.norm_to_raw_map,
        views.raw_to_norm_map,
    )

    assert views.normalized_lookup_text == "é đau"
    assert mapper.recover_raw_span_from_normalized_match(0, 1) == (0, 2)
    assert mapper.recover_raw_text_from_normalized_match(0, 1) == "e\u0301"


def test_line_windows_preserve_crlf_and_empty_lines():
    raw_text = "first\r\n\r\nthird\n"
    windows = build_line_windows(raw_text)

    assert [(window.text, window.start, window.end) for window in windows] == [
        ("first", 0, 5),
        ("", 7, 7),
        ("third", 9, 14),
        ("", 15, 15),
    ]


def test_sentence_windows_keep_punctuation_and_raw_offsets():
    raw_text = "Đau bụng. Sốt cao! WBC: 14,43\nỔn định?"
    windows = build_sentence_windows(raw_text)

    assert [window.text for window in windows] == [
        "Đau bụng.",
        "Sốt cao!",
        "WBC: 14,43",
        "Ổn định?",
    ]
    assert all(raw_text[window.start:window.end] == window.text for window in windows)


def test_model_windows_overlap_without_changing_raw_text():
    raw_text = "alpha beta gamma delta epsilon zeta eta theta"
    windows = build_model_windows(raw_text, max_chars=18, overlap_chars=5)

    assert len(windows) > 1
    assert windows[0].start == 0
    assert windows[-1].end == len(raw_text)
    assert all(raw_text[window.start:window.end] == window.text for window in windows)
    assert any(left.end > right.start for left, right in zip(windows, windows[1:]))


def test_token_offsets_include_words_and_punctuation():
    raw_text = "WBC: 14,43"
    views = preprocess_text(raw_text)

    assert [token.text for token in views.token_offsets] == ["WBC", ":", "14", ",", "43"]
    assert all(raw_text[token.start:token.end] == token.text for token in views.token_offsets)
    assert all(token.normalized_start is not None for token in views.token_offsets)
    assert all(token.normalized_end is not None for token in views.token_offsets)


def test_preprocess_rejects_invalid_model_window_parameters():
    try:
        build_model_windows("abc", max_chars=4, overlap_chars=4)
    except ValueError as error:
        assert "overlap_chars" in str(error)
    else:
        raise AssertionError("Expected invalid overlap to raise ValueError")

    try:
        build_model_windows("abc", max_chars=0)
    except ValueError as error:
        assert "max_chars" in str(error)
    else:
        raise AssertionError("Expected invalid max_chars to raise ValueError")
