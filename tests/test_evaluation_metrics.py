from __future__ import annotations

from src.evaluation.metrics import compute_assertion_metrics, compute_candidate_metrics, counts_by_type
from src.evaluation.models import EvalEntity, EntityPair, PRFCounts


def E(
    start: int,
    end: int,
    entity_type: str,
    *,
    assertions: tuple[str, ...] = (),
    candidates: tuple[str, ...] = (),
    index: int = 0,
) -> EvalEntity:
    return EvalEntity("1", "x", start, end, entity_type, assertions, candidates, index)


def test_prf_counts_zero_division() -> None:
    counts = PRFCounts()
    assert counts.precision == 0.0
    assert counts.recall == 0.0
    assert counts.f1 == 0.0


def test_prf_counts_values() -> None:
    counts = PRFCounts(tp=2, fp=1, fn=3)
    assert round(counts.precision, 6) == 0.666667
    assert counts.recall == 0.4
    assert round(counts.f1, 6) == 0.5


def test_counts_by_type() -> None:
    pred_match = E(0, 3, "TRIỆU_CHỨNG")
    gold_match = E(0, 3, "TRIỆU_CHỨNG")
    pred_fp = E(4, 7, "CHẨN_ĐOÁN")
    gold_fn = E(8, 11, "THUỐC")
    counts = counts_by_type([pred_match, pred_fp], [gold_match, gold_fn], [EntityPair(pred_match, gold_match, "exact")])
    assert counts["TRIỆU_CHỨNG"].tp == 1
    assert counts["CHẨN_ĐOÁN"].fp == 1
    assert counts["THUỐC"].fn == 1


def test_assertion_metrics() -> None:
    pairs = [
        EntityPair(E(0, 3, "TRIỆU_CHỨNG", assertions=("isNegated",)), E(0, 3, "TRIỆU_CHỨNG", assertions=("isNegated",)), "exact"),
        EntityPair(E(4, 7, "CHẨN_ĐOÁN"), E(4, 7, "CHẨN_ĐOÁN", assertions=("isHistorical",)), "exact"),
    ]
    metrics = compute_assertion_metrics(pairs)
    assert metrics["total_matched_assertable"] == 2
    assert metrics["exact_set_match_count"] == 1
    assert metrics["mismatch_count"] == 1
    assert metrics["by_label"]["isNegated"]["tp"] == 1
    assert metrics["by_label"]["isHistorical"]["fn"] == 1


def test_candidate_hit_metrics_skip_empty_gold() -> None:
    pairs = [
        EntityPair(E(0, 3, "CHẨN_ĐOÁN", candidates=("J18.9",)), E(0, 3, "CHẨN_ĐOÁN", candidates=("J18.9",)), "exact"),
        EntityPair(E(4, 7, "THUỐC", candidates=("1191",)), E(4, 7, "THUỐC", candidates=()), "exact"),
    ]
    metrics = compute_candidate_metrics(pairs, skip_empty_gold_candidates=True)
    assert metrics["total_evaluable"] == 1
    assert metrics["hit_count"] == 1
    assert metrics["skipped_empty_gold"] == 1


def test_candidate_hit_metrics_wrong_and_partial() -> None:
    pairs = [
        EntityPair(E(0, 3, "CHẨN_ĐOÁN", candidates=("J18.9", "J18")), E(0, 3, "CHẨN_ĐOÁN", candidates=("J18", "J19")), "exact"),
        EntityPair(E(4, 7, "THUỐC", candidates=("1191",)), E(4, 7, "THUỐC", candidates=("6809",)), "exact"),
    ]
    metrics = compute_candidate_metrics(pairs)
    assert metrics["total_evaluable"] == 2
    assert metrics["hit_count"] == 1
    assert metrics["mismatch_counts"]["partial_candidate"] == 1
    assert metrics["mismatch_counts"]["wrong_candidate"] == 1
    assert metrics["mismatch_count"] == 2