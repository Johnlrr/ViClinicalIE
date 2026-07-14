from __future__ import annotations

from src.data_types import FinalEntity
from src.postprocess.span_utils import contains, overlap_len, span_iou, validate_entity_offset, with_span


def _entity(raw_text: str, text: str, entity_type: str = "TRIỆU_CHỨNG") -> FinalEntity:
    start = raw_text.index(text)
    return FinalEntity(text=text, start=start, end=start + len(text), type=entity_type)


def test_span_iou_no_overlap() -> None:
    first = FinalEntity(text="abc", start=0, end=3, type="TRIỆU_CHỨNG")
    second = FinalEntity(text="def", start=4, end=7, type="TRIỆU_CHỨNG")

    assert overlap_len(first, second) == 0
    assert span_iou(first, second) == 0.0


def test_span_iou_partial_overlap() -> None:
    first = FinalEntity(text="abcd", start=0, end=4, type="TRIỆU_CHỨNG")
    second = FinalEntity(text="cdef", start=2, end=6, type="TRIỆU_CHỨNG")

    assert overlap_len(first, second) == 2
    assert span_iou(first, second) == 2 / 6


def test_contains() -> None:
    outer = FinalEntity(text="đau bụng vùng hạ sườn phải", start=0, end=27, type="TRIỆU_CHỨNG")
    inner = FinalEntity(text="đau bụng", start=0, end=8, type="TRIỆU_CHỨNG")

    assert contains(outer, inner)
    assert not contains(inner, outer)


def test_with_span_rebuilds_raw_text() -> None:
    raw_text = "Không sốt."
    entity = _entity(raw_text, "Không sốt")

    updated = with_span(entity, raw_text, raw_text.index("sốt"), raw_text.index("sốt") + len("sốt"))

    assert updated.text == "sốt"
    assert raw_text[updated.start : updated.end] == updated.text


def test_validate_entity_offset_detects_mismatch() -> None:
    raw_text = "Không sốt."
    entity = FinalEntity(text="ho", start=6, end=9, type="TRIỆU_CHỨNG")

    assert validate_entity_offset(entity, raw_text).startswith("offset_mismatch")