from __future__ import annotations

from streamlit_app.data_loader import get_position, records_to_dataframe
from streamlit_app.highlight import HighlightSpan, render_highlighted_text
from streamlit_app.tables import compare_entity_rows, flatten_error_rows


def test_get_position_handles_valid_and_invalid_records() -> None:
    assert get_position({"position": [2, 5]}) == (2, 5)
    assert get_position({"position": ["2", "5"]}) == (2, 5)
    assert get_position({"position": []}) == (0, 0)
    assert get_position({}) == (0, 0)


def test_records_to_dataframe_flattens_submission_records() -> None:
    frame = records_to_dataframe(
        [
            {
                "text": "sốt",
                "position": [6, 9],
                "type": "TRIỆU_CHỨNG",
                "assertions": ["isNegated"],
                "candidates": [],
            }
        ]
    )

    assert frame.iloc[0]["text"] == "sốt"
    assert frame.iloc[0]["start"] == 6
    assert frame.iloc[0]["assertions"] == "isNegated"


def test_render_highlighted_text_escapes_html_and_keeps_span_text() -> None:
    raw = "Không <sốt>."
    html = render_highlighted_text(raw, [HighlightSpan(6, 11, "gold: TRIỆU_CHỨNG", "gold")])

    assert "&lt;sốt&gt;" in html
    assert "<mark" in html


def test_flatten_error_rows_handles_pred_gold_records() -> None:
    frame = flatten_error_rows(
        [
            {
                "file_id": "1",
                "category": "span_mismatch",
                "subcategory": "pred_too_short",
                "pred": {"text": "sốt", "position": [6, 9], "type": "TRIỆU_CHỨNG"},
                "gold": {"text": "không sốt", "position": [0, 9], "type": "TRIỆU_CHỨNG"},
            }
        ]
    )

    assert frame.iloc[0]["file_id"] == "1"
    assert frame.iloc[0]["pred_text"] == "sốt"
    assert frame.iloc[0]["gold_position"] == "0:9"


def test_compare_entity_rows_marks_exact_match() -> None:
    record = {"text": "sốt", "position": [6, 9], "type": "TRIỆU_CHỨNG"}
    frame = compare_entity_rows([record], [record])

    assert set(frame["status"]) == {"exact_match"}
