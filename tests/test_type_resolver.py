from __future__ import annotations

from src.data_types import SpanCandidate
from src.type_resolution.resolver import TypeResolver


def _candidate(raw: str, text: str, *, source: str, raw_type: str | None, score: float = 0.8, features=None) -> SpanCandidate:
    start = raw.index(text)
    end = start + len(text)
    return SpanCandidate(
        text=text,
        start=start,
        end=end,
        raw_type=raw_type,
        source=source,
        score=score,
        context_left=raw[max(0, start - 80) : start],
        context_right=raw[end : end + 80],
        features=dict(features or {}),
    )


def test_resolves_lab_result_priority() -> None:
    raw = "troponin 0.01"
    resolver = TypeResolver()
    entities = resolver.resolve([_candidate(raw, "0.01", source="lab_result_rule", raw_type="KẾT_QUẢ_XÉT_NGHIỆM")], raw)

    assert entities[0].type == "KẾT_QUẢ_XÉT_NGHIỆM"
    assert raw[entities[0].start : entities[0].end] == entities[0].text


def test_resolves_lab_and_imaging_as_test_names() -> None:
    raw = "troponin và chụp x-quang ngực"
    candidates = [
        _candidate(raw, "troponin", source="lab_rule", raw_type="TÊN_XÉT_NGHIỆM"),
        _candidate(raw, "chụp x-quang ngực", source="imaging_rule", raw_type="TÊN_XÉT_NGHIỆM"),
    ]

    entities = TypeResolver().resolve(candidates, raw)

    assert [entity.type for entity in entities] == ["TÊN_XÉT_NGHIỆM", "TÊN_XÉT_NGHIỆM"]


def test_resolves_drug_with_context() -> None:
    raw = "được cho aspirin 325mg x 1"
    entity = TypeResolver().resolve([_candidate(raw, "aspirin 325mg x 1", source="drug_rule", raw_type="THUỐC", features={"strength": "325mg"})], raw)[0]

    assert entity.type == "THUỐC"
    assert entity.confidence >= 0.9


def test_resolves_symptom_and_diagnosis_problem_rules() -> None:
    raw = "khó thở và viêm túi mật cấp"
    candidates = [
        _candidate(raw, "khó thở", source="problem_rule", raw_type="TRIỆU_CHỨNG", features={"rule": "symptom_head"}),
        _candidate(raw, "viêm túi mật cấp", source="problem_rule", raw_type="CHẨN_ĐOÁN", features={"rule": "disease_head"}),
    ]

    entities = TypeResolver().resolve(candidates, raw)

    assert [(entity.text, entity.type) for entity in entities] == [("khó thở", "TRIỆU_CHỨNG"), ("viêm túi mật cấp", "CHẨN_ĐOÁN")]


def test_exact_span_conflict_prefers_drug_and_logs_conflict() -> None:
    raw = "aspirin"
    candidates = [
        _candidate(raw, "aspirin", source="dictionary", raw_type="TRIỆU_CHỨNG", score=0.7),
        _candidate(raw, "aspirin", source="drug_rule", raw_type="THUỐC", score=0.8),
    ]
    resolver = TypeResolver()
    entities = resolver.resolve(candidates, raw)

    assert entities[0].type == "THUỐC"
    assert len(resolver.conflicts) == 1
    assert resolver.conflicts[0].chosen_type == "THUỐC"


def test_drug_without_context_keeps_entity_with_warning_and_lower_confidence() -> None:
    raw = "caffeine"
    entity = TypeResolver().resolve([_candidate(raw, "caffeine", source="drug_rule", raw_type="THUỐC")], raw)[0]

    assert entity.type == "THUỐC"
    assert entity.confidence < 0.9
    assert "drug_without_context" in entity.provenance["warnings"]


def test_same_type_exact_span_duplicates_are_not_type_conflicts() -> None:
    raw = "khó thở"
    candidates = [
        _candidate(raw, "khó thở", source="dictionary", raw_type="TRIỆU_CHỨNG", score=0.7),
        _candidate(raw, "khó thở", source="problem_rule", raw_type="TRIỆU_CHỨNG", score=0.8, features={"rule": "symptom_head"}),
    ]
    resolver = TypeResolver()
    entities = resolver.resolve(candidates, raw)

    assert entities[0].type == "TRIỆU_CHỨNG"
    assert resolver.conflicts == []
    assert resolver.duplicate_exact_span_count == 1
    assert entities[0].provenance["exact_span_candidate_count"] == 2


def test_type_priority_beats_source_priority_for_exact_span() -> None:
    raw = "caffeine"
    candidates = [
        _candidate(raw, "caffeine", source="problem_rule", raw_type="CHẨN_ĐOÁN", score=0.95, features={"rule": "disease_head"}),
        _candidate(raw, "caffeine", source="dictionary", raw_type="THUỐC", score=0.6),
    ]
    resolver = TypeResolver()
    entities = resolver.resolve(candidates, raw)

    assert entities[0].type == "THUỐC"
    assert len(resolver.conflicts) == 1
    assert resolver.conflicts[0].rejected_types == ["CHẨN_ĐOÁN"]


def test_unresolved_invalid_type_is_logged_once() -> None:
    raw = "unknown"
    resolver = TypeResolver()
    entities = resolver.resolve([_candidate(raw, "unknown", source="mystery", raw_type=None)], raw)

    assert entities == []
    assert len(resolver.unresolved) == 1
    assert resolver.unresolved[0]["reason"] == "invalid_or_missing_raw_type"


def test_different_span_overlaps_are_kept_and_logged() -> None:
    raw = "đau bụng vùng hạ sườn phải"
    candidates = [
        _candidate(raw, "đau bụng", source="dictionary", raw_type="TRIỆU_CHỨNG"),
        _candidate(raw, "đau bụng vùng hạ sườn phải", source="problem_rule", raw_type="TRIỆU_CHỨNG", features={"rule": "symptom_head"}),
    ]
    resolver = TypeResolver()
    entities = resolver.resolve(candidates, raw)

    assert len(entities) == 2
    assert len(resolver.overlaps) == 1
    assert resolver.overlaps[0].overlap_text == "đau bụng"
    for entity in entities:
        assert raw[entity.start : entity.end] == entity.text
