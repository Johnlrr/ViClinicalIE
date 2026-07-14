from __future__ import annotations

from src.evaluation.models import EvalEntity
from src.evaluation.span_matcher import containment_ratio, exact_match_entities, relaxed_match_entities, span_iou


def E(start: int, end: int, entity_type: str = "TRIỆU_CHỨNG", index: int = 0) -> EvalEntity:
    return EvalEntity(file_id="1", text="x", start=start, end=end, type=entity_type, index=index)


def test_span_iou_no_overlap() -> None:
    assert span_iou(E(0, 3), E(4, 7)) == 0.0


def test_span_iou_partial_overlap() -> None:
    assert round(span_iou(E(0, 10), E(5, 15)), 6) == 0.333333


def test_containment_ratio() -> None:
    assert containment_ratio(E(0, 20), E(5, 10)) == 1.0


def test_exact_match_single_entity() -> None:
    pairs, unmatched_pred, unmatched_gold = exact_match_entities([E(0, 3)], [E(0, 3)])
    assert len(pairs) == 1
    assert unmatched_pred == []
    assert unmatched_gold == []


def test_exact_match_handles_duplicate_gold() -> None:
    pairs, unmatched_pred, unmatched_gold = exact_match_entities([E(0, 3, index=0)], [E(0, 3, index=0), E(0, 3, index=1)])
    assert len(pairs) == 1
    assert unmatched_pred == []
    assert len(unmatched_gold) == 1


def test_exact_match_handles_duplicate_predictions() -> None:
    pairs, unmatched_pred, unmatched_gold = exact_match_entities([E(0, 3, index=0), E(0, 3, index=1)], [E(0, 3)])
    assert len(pairs) == 1
    assert len(unmatched_pred) == 1
    assert unmatched_gold == []


def test_exact_match_leaves_type_mismatch_unmatched() -> None:
    pairs, unmatched_pred, unmatched_gold = exact_match_entities([E(0, 3, "CHẨN_ĐOÁN")], [E(0, 3, "TRIỆU_CHỨNG")])
    assert pairs == []
    assert len(unmatched_pred) == 1
    assert len(unmatched_gold) == 1


def test_relaxed_match_same_type_iou() -> None:
    pairs, unmatched_pred, unmatched_gold = relaxed_match_entities([E(0, 10)], [E(2, 10)], iou_threshold=0.5, containment_threshold=0.95)
    assert len(pairs) == 1
    assert unmatched_pred == []
    assert unmatched_gold == []


def test_relaxed_match_same_type_containment() -> None:
    pairs, _, _ = relaxed_match_entities([E(0, 50)], [E(10, 20)], iou_threshold=0.5, containment_threshold=0.8)
    assert len(pairs) == 1
    assert pairs[0].containment_ratio == 1.0


def test_relaxed_does_not_match_different_type() -> None:
    pairs, unmatched_pred, unmatched_gold = relaxed_match_entities([E(0, 10, "CHẨN_ĐOÁN")], [E(0, 10, "TRIỆU_CHỨNG")])
    assert pairs == []
    assert len(unmatched_pred) == 1
    assert len(unmatched_gold) == 1


def test_relaxed_greedy_prefers_highest_iou() -> None:
    pred = E(0, 10, index=0)
    weak_gold = E(0, 20, index=0)
    strong_gold = E(0, 10, index=1)
    pairs, _, unmatched_gold = relaxed_match_entities([pred], [weak_gold, strong_gold], iou_threshold=0.1, containment_threshold=0.1)
    assert len(pairs) == 1
    assert pairs[0].gold is strong_gold
    assert unmatched_gold == [weak_gold]