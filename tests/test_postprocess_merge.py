from __future__ import annotations

from src.data_types import FinalEntity
from src.postprocess.merge import merge_exact_duplicates, resolve_different_type_overlaps, resolve_same_type_overlaps


def _entity(raw_text: str, text: str, entity_type: str, occurrence: int = 0, **kwargs) -> FinalEntity:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = raw_text.index(text, cursor)
        cursor = start + len(text)
    return FinalEntity(text=text, start=start, end=start + len(text), type=entity_type, **kwargs)


def test_merge_exact_duplicates_keeps_highest_confidence() -> None:
    raw_text = "sốt"
    low = FinalEntity(text="sốt", start=0, end=3, type="TRIỆU_CHỨNG", confidence=0.4)
    high = FinalEntity(text="sốt", start=0, end=3, type="TRIỆU_CHỨNG", confidence=0.9)

    merged, decisions = merge_exact_duplicates([low, high], raw_text, {})

    assert len(merged) == 1
    assert merged[0].confidence == 0.9
    assert len(decisions) == 1


def test_merge_exact_duplicates_unions_assertions_and_candidates() -> None:
    raw_text = "tăng huyết áp"
    first = FinalEntity(text=raw_text, start=0, end=len(raw_text), type="CHẨN_ĐOÁN", assertions=["isHistorical"], candidates=["I10"])
    second = FinalEntity(text=raw_text, start=0, end=len(raw_text), type="CHẨN_ĐOÁN", assertions=["isNegated"], candidates=["I10", "I11"])

    merged, _ = merge_exact_duplicates([first, second], raw_text, {})

    assert merged[0].assertions == ["isNegated", "isHistorical"]
    assert merged[0].candidates == ["I10", "I11"]


def test_same_type_symptom_keeps_longer_clean_span() -> None:
    raw_text = "đau bụng vùng hạ sườn phải"
    short = _entity(raw_text, "đau bụng", "TRIỆU_CHỨNG", confidence=0.5)
    long = _entity(raw_text, raw_text, "TRIỆU_CHỨNG", confidence=0.5)

    resolved, decisions = resolve_same_type_overlaps([short, long], raw_text, {})

    assert [entity.text for entity in resolved] == [raw_text]
    assert len(decisions) == 1


def test_same_type_drug_keeps_strength_span() -> None:
    raw_text = "metoprolol 25mg"
    name = _entity(raw_text, "metoprolol", "THUỐC", confidence=0.8, provenance={"rxnorm_linking": {"parsed": {}}})
    strength = _entity(
        raw_text,
        raw_text,
        "THUỐC",
        confidence=0.8,
        provenance={"rxnorm_linking": {"parsed": {"strength_value": 25.0}}},
    )

    resolved, _ = resolve_same_type_overlaps([name, strength], raw_text, {})

    assert [entity.text for entity in resolved] == [raw_text]


def test_lab_name_and_result_not_merged() -> None:
    raw_text = "Na 140"
    name = _entity(raw_text, "Na", "TÊN_XÉT_NGHIỆM", provenance={"chosen_source": "lab_rule"})
    result = _entity(raw_text, "140", "KẾT_QUẢ_XÉT_NGHIỆM", provenance={"chosen_source": "lab_result_rule"})

    same_type, same_decisions = resolve_same_type_overlaps([name, result], raw_text, {})
    different_type, different_decisions = resolve_different_type_overlaps(same_type, raw_text, {})

    assert len(same_type) == 2
    assert len(same_decisions) == 0
    assert len(different_type) == 2
    assert len(different_decisions) == 0


def test_different_type_lab_rule_beats_problem_overlap() -> None:
    raw_text = "siêu âm tim"
    lab = _entity(raw_text, raw_text, "TÊN_XÉT_NGHIỆM", confidence=0.7, provenance={"chosen_source": "imaging_rule"})
    problem = _entity(raw_text, raw_text, "CHẨN_ĐOÁN", confidence=0.9)

    resolved, decisions = resolve_different_type_overlaps([problem, lab], raw_text, {})

    assert [entity.type for entity in resolved] == ["TÊN_XÉT_NGHIỆM"]
    assert decisions[0].reason == "test_name_source_priority"


def test_different_type_drug_with_rx_candidate_beats_problem_overlap() -> None:
    raw_text = "aspirin"
    drug = _entity(raw_text, raw_text, "THUỐC", candidates=["1191"], confidence=0.7)
    symptom = _entity(raw_text, raw_text, "TRIỆU_CHỨNG", confidence=0.9)

    resolved, decisions = resolve_different_type_overlaps([symptom, drug], raw_text, {})

    assert [entity.type for entity in resolved] == ["THUỐC"]
    assert decisions[0].reason == "linked_drug_priority"