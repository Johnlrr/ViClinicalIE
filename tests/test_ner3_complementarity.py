from __future__ import annotations

from src.data_types import SpanCandidate
from src.ner.complementarity import analyze_complementarity


def _candidate(text, start, end, entity_type, source):
    return SpanCandidate(text, start, end, entity_type, source, .8)


def test_complementarity_categories_are_one_to_one_and_deterministic() -> None:
    gliner = [
        _candidate("đau ngực", 0, 8, "TRIỆU_CHỨNG", "gliner"),
        _candidate("aspirin", 10, 17, "THUỐC", "gliner"),
        _candidate("sốt cao", 20, 27, "TRIỆU_CHỨNG", "gliner"),
    ]
    experts = [
        _candidate("đau ngực", 0, 8, "TRIỆU_CHỨNG", "problem_rule"),
        _candidate("aspirin", 10, 17, "CHẨN_ĐOÁN", "dictionary"),
        _candidate("sốt", 20, 23, "TRIỆU_CHỨNG", "problem_rule"),
        _candidate("ho", 30, 32, "TRIỆU_CHỨNG", "problem_rule"),
    ]
    report = analyze_complementarity(gliner, experts, near_iou_threshold=.3)
    assert report["category_counts"] == {
        "exact_agreement": 1, "exact_type_conflict": 1,
        "near_overlap_agreement": 1, "v1_only": 1,
    }


def test_structured_anchor_opportunity_is_reported_not_fused() -> None:
    gliner = [_candidate("aspirin", 0, 7, "THUỐC", "gliner")]
    experts = [_candidate("aspirin 25mg", 0, 12, "THUỐC", "drug_rule")]
    report = analyze_complementarity(gliner, experts, near_iou_threshold=.5)
    assert report["structured_anchor_opportunities"][0]["relation"] == "expert_contains_gliner"


def test_duplicate_inputs_do_not_double_count_and_gold_utility_is_reported() -> None:
    candidate = _candidate("sốt", 0, 3, "TRIỆU_CHỨNG", "gliner")
    expert = _candidate("sốt", 0, 3, "TRIỆU_CHỨNG", "problem_rule")
    report = analyze_complementarity(
        [candidate, candidate], [expert, expert],
        gold_records=[{"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG"}],
    )
    assert report["category_counts"] == {"exact_agreement": 1}
    assert report["gold_utility"]["gliner"]["exact_gold_tp"] == 1
    assert report["by_source"]["problem_rule"]["gold_utility"]["source_only_fp"] == 0


def test_wrong_type_structured_anchor_is_not_reported() -> None:
    gliner = [_candidate("aspirin", 0, 7, "CHẨN_ĐOÁN", "gliner")]
    experts = [_candidate("aspirin 25mg", 0, 12, "THUỐC", "drug_rule")]
    assert analyze_complementarity(gliner, experts)["structured_anchor_opportunities"] == []