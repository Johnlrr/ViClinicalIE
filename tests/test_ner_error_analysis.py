from __future__ import annotations

from src.evaluation.error_analysis import span_mismatch_subtype
from src.evaluation.models import EvalEntity


def _entity(start: int, end: int) -> EvalEntity:
    return EvalEntity("1", "x", start, end, "TRIỆU_CHỨNG")


def test_boundary_error_subtypes() -> None:
    gold = _entity(2, 8)
    assert span_mismatch_subtype(_entity(2, 7), gold) == "right_boundary_error"
    assert span_mismatch_subtype(_entity(3, 8), gold) == "left_boundary_error"
    assert span_mismatch_subtype(_entity(1, 9), gold) == "both_boundary_error"