from __future__ import annotations

from src.data_types import SpanCandidate
from src.ner.evidence_adapter import normalize_candidates
from src.ner.simple_fusion import resolve_replay, resolve_replay_trace


def _candidate(raw, text, entity_type, source, score=.8, features=None):
    start = raw.index(text)
    return SpanCandidate(text, start, start + len(text), entity_type, source, score, features=dict(features or {}))


def test_naive_union_dedupes_exact_same_type_but_keeps_type_conflict() -> None:
    raw = "aspirin"
    candidates = [
        _candidate(raw, raw, "THUỐC", "gliner"),
        _candidate(raw, raw, "THUỐC", "dictionary"),
    ]
    entities = resolve_replay(candidates, raw, mode="naive_union")
    assert [str(entity.type) for entity in entities] == ["THUỐC"]
    assert entities[0].provenance["ner3_exact_sources"] == ["dictionary", "gliner"]


def test_naive_union_keeps_cross_system_same_span_type_conflict() -> None:
    raw = "aspirin"
    candidates = [
        _candidate(raw, raw, "THUỐC", "gliner"),
        _candidate(raw, raw, "CHẨN_ĐOÁN", "dictionary"),
    ]
    entities = resolve_replay(candidates, raw, mode="naive_union")
    assert sorted(str(entity.type) for entity in entities) == ["CHẨN_ĐOÁN", "THUỐC"]
    assert all(entity.provenance["ner3_fusion_mode"] == "naive_union_exact_dedup" for entity in entities)


def test_simple_fusion_resolves_exact_conflict_and_keeps_gliner_only() -> None:
    raw = "aspirin và chóng mặt"
    candidates = [
        _candidate(raw, "aspirin", "THUỐC", "gliner"),
        _candidate(raw, "aspirin", "THUỐC", "drug_rule", features={"strength": "25mg"}),
        _candidate(raw, "aspirin", "CHẨN_ĐOÁN", "dictionary"),
        _candidate(raw, "chóng mặt", "TRIỆU_CHỨNG", "gliner"),
    ]
    entities = resolve_replay(candidates, raw, mode="simple_fusion")
    assert [(entity.text, entity.type) for entity in entities] == [("aspirin", "THUỐC"), ("chóng mặt", "TRIỆU_CHỨNG")]
    assert len(entities[0].provenance["source_candidates"]) == 3


def test_simple_fusion_does_not_merge_near_overlap() -> None:
    raw = "đau bụng dữ dội"
    candidates = [
        _candidate(raw, "đau bụng", "TRIỆU_CHỨNG", "gliner"),
        _candidate(raw, raw, "TRIỆU_CHỨNG", "problem_rule", features={"rule": "symptom_head"}),
    ]
    assert len(resolve_replay(candidates, raw, mode="simple_fusion")) == 2


def test_simple_fusion_uses_same_type_structured_anchor_and_keeps_provenance() -> None:
    raw = "aspirin 25mg"
    candidates = normalize_candidates([
        _candidate(raw, "aspirin", "THUỐC", "gliner", score=.91),
        _candidate(raw, raw, "THUỐC", "drug_rule", score=.78, features={"strength": "25mg"}),
    ])
    result = resolve_replay_trace(candidates, raw, mode="simple_fusion")
    assert [(entity.text, entity.type) for entity in result.entities] == [(raw, "THUỐC")]
    assert result.anchor_events[0]["gliner_span"] == [0, 7]
    source_features = result.entities[0].provenance["chosen_candidate_features"]
    assert source_features["ner3_structured_anchor"]["semantic_proposals"][0]["source"] == "gliner"
    assert result.entities[0].confidence != .91  # raw cross-source scores are not added or reused as confidence


def test_structured_anchor_rejects_wrong_type_and_problem_near_overlap() -> None:
    raw = "aspirin 25mg và đau bụng dữ dội"
    candidates = [
        _candidate(raw, "aspirin", "CHẨN_ĐOÁN", "gliner"),
        _candidate(raw, "aspirin 25mg", "THUỐC", "drug_rule"),
        _candidate(raw, "đau bụng", "TRIỆU_CHỨNG", "gliner"),
        _candidate(raw, "đau bụng dữ dội", "TRIỆU_CHỨNG", "problem_rule", features={"rule": "symptom_head"}),
    ]
    result = resolve_replay_trace(candidates, raw, mode="simple_fusion")
    assert result.anchor_events == []
    assert len(result.entities) == 4


def test_simple_fusion_has_no_exact_duplicate_output() -> None:
    raw = "aspirin"
    candidates = [
        _candidate(raw, raw, "THUỐC", "gliner"),
        _candidate(raw, raw, "THUỐC", "drug_rule"),
        _candidate(raw, raw, "THUỐC", "dictionary"),
    ]
    entities = resolve_replay(candidates, raw, mode="simple_fusion")
    keys = [(entity.start, entity.end, str(entity.type)) for entity in entities]
    assert len(keys) == len(set(keys)) == 1