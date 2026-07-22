from __future__ import annotations

from src.data_types import SpanCandidate
from src.ner.evidence_adapter import EVIDENCE_SCHEMA_VERSION, normalize_candidate_evidence, validate_candidate_evidence


def test_normalizes_gliner_evidence_without_losing_features() -> None:
    candidate = SpanCandidate("sốt", 0, 3, "TRIỆU_CHỨNG", "gliner", .7, section="CURRENT", features={
        "window_id": "w0", "pass_name": "full", "prompt_label": "symptom",
        "raw_model_score": .7, "supporting_windows": ["w0"], "proposal_evidence": [{"window_id": "w0"}],
    })
    normalized = normalize_candidate_evidence(candidate)
    assert normalized.features["window_id"] == "w0"
    evidence = normalized.features["evidence"]
    assert evidence["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert evidence["source_family"] == "semantic_backbone"
    assert evidence["score_kind"] == "gliner_probability"
    assert evidence["pass"] == "full"
    assert evidence["proposal_evidence"] == [{"window_id": "w0"}]
    assert validate_candidate_evidence(normalized) == []


def test_normalizes_structural_pair_and_anchor() -> None:
    candidate = SpanCandidate("troponin", 0, 8, "TÊN_XÉT_NGHIỆM", "lab_rule", .82, features={"pair_id": "p1"})
    evidence = normalize_candidate_evidence(candidate).features["evidence"]
    assert evidence["role"] == "structural_pair"
    assert evidence["structural_pair_id"] == "p1"
    assert evidence["anchor_kind"] == "lab_test"


def test_normalization_is_idempotent_and_does_not_change_original() -> None:
    candidate = SpanCandidate("aspirin", 0, 7, "THUỐC", "drug_rule", .78, features={"strength": "25mg"})
    first = normalize_candidate_evidence(candidate)
    second = normalize_candidate_evidence(first)
    assert candidate.features == {"strength": "25mg"}
    assert second.features == first.features
    assert second.score == .78