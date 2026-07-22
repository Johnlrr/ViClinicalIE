from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from src.data_types import SpanCandidate


EVIDENCE_SCHEMA_VERSION = "ner3-evidence-v1"
SOURCE_FAMILY = {
    "gliner": "semantic_backbone",
    "drug_rule": "structured_expert",
    "lab_rule": "structured_expert",
    "lab_result_rule": "structured_expert",
    "imaging_rule": "structured_expert",
    "problem_rule": "problem_expert",
    "dictionary": "dictionary",
}
SOURCE_ROLE = {
    "gliner": "proposal",
    "drug_rule": "precision_anchor",
    "lab_rule": "structural_pair",
    "lab_result_rule": "structural_pair",
    "imaging_rule": "precision_anchor",
    "problem_rule": "type_evidence",
    "dictionary": "precision_anchor",
}
SCORE_KIND = {"gliner": "gliner_probability"}

KNOWN_SOURCES = frozenset(SOURCE_FAMILY)


def normalize_candidate_evidence(candidate: SpanCandidate) -> SpanCandidate:
    features = deepcopy(candidate.features)
    evidence = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "source_name": candidate.source,
        "source_family": SOURCE_FAMILY.get(candidate.source, "other"),
        "role": SOURCE_ROLE.get(candidate.source, "proposal"),
        "proposed_type": candidate.raw_type,
        "raw_score": float(candidate.score),
        "score_kind": SCORE_KIND.get(candidate.source, "deterministic_rule_confidence"),
        "section": candidate.section,
        "subsection": candidate.subsection,
        "structural_pair_id": features.get("pair_id"),
        "anchor_kind": _anchor_kind(candidate.source, features),
    }
    if candidate.source == "gliner":
        evidence["pass"] = features.get("pass_name")
        evidence["prompt_label"] = features.get("prompt_label")
        evidence["raw_model_score"] = features.get("raw_model_score", candidate.score)
        evidence["window_id"] = features.get("window_id")
        evidence["supporting_windows"] = deepcopy(features.get("supporting_windows", []))
        evidence["supporting_passes"] = deepcopy(features.get("supporting_passes", []))
        evidence["proposal_evidence"] = deepcopy(features.get("proposal_evidence", []))
    features["evidence"] = evidence
    return _copy_candidate(candidate, features)


def validate_candidate_evidence(candidate: SpanCandidate) -> list[str]:
    errors: list[str] = []
    evidence = candidate.features.get("evidence")
    if not isinstance(evidence, Mapping):
        return ["missing_evidence"]
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append("invalid_evidence_schema")
    if evidence.get("source_name") != candidate.source:
        errors.append("evidence_source_mismatch")
    if evidence.get("proposed_type") != candidate.raw_type:
        errors.append("evidence_type_mismatch")
    expected_score_kind = SCORE_KIND.get(candidate.source, "deterministic_rule_confidence")
    if evidence.get("score_kind") != expected_score_kind:
        errors.append("invalid_score_kind")
    try:
        raw_score = float(evidence.get("raw_score"))
    except (TypeError, ValueError):
        raw_score = float("nan")
    if raw_score != float(candidate.score):
        errors.append("evidence_score_mismatch")
    if evidence.get("source_family") != SOURCE_FAMILY.get(candidate.source, "other"):
        errors.append("evidence_source_family_mismatch")
    if evidence.get("role") != SOURCE_ROLE.get(candidate.source, "proposal"):
        errors.append("evidence_role_mismatch")
    if evidence.get("section") != candidate.section or evidence.get("subsection") != candidate.subsection:
        errors.append("evidence_section_mismatch")
    if not evidence.get("score_kind"):
        errors.append("missing_score_kind")
    if candidate.source in {"lab_rule", "lab_result_rule"} and candidate.features.get("pair_id"):
        if evidence.get("structural_pair_id") != candidate.features.get("pair_id"):
            errors.append("structural_pair_mismatch")
    if candidate.source == "gliner":
        required = ("pass", "prompt_label", "raw_model_score", "window_id")
        if any(evidence.get(key) is None for key in required):
            errors.append("missing_gliner_provenance")
    return errors


def candidate_evidence_row(candidate: SpanCandidate) -> dict[str, Any]:
    return {
        "text": candidate.text,
        "position": [candidate.start, candidate.end],
        "raw_type": candidate.raw_type,
        "source": candidate.source,
        "score": candidate.score,
        "evidence": deepcopy(candidate.features.get("evidence", {})),
        "features": deepcopy(candidate.features),
    }


def _copy_candidate(candidate: SpanCandidate, features: dict[str, Any]) -> SpanCandidate:
    return SpanCandidate(
        text=candidate.text, start=candidate.start, end=candidate.end,
        raw_type=candidate.raw_type, source=candidate.source, score=candidate.score,
        section=candidate.section, subsection=candidate.subsection,
        context_left=candidate.context_left, context_right=candidate.context_right,
        features=features,
    )


def normalize_candidates(candidates: list[SpanCandidate]) -> list[SpanCandidate]:
    return [normalize_candidate_evidence(candidate) for candidate in candidates]


def _anchor_kind(source: str, features: Mapping[str, Any]) -> str | None:
    if source == "drug_rule":
        return "drug_alias"
    if source == "lab_rule":
        return "lab_test"
    if source == "lab_result_rule":
        return "imaging_result" if features.get("pattern") == "imaging_test_plus_result" else "lab_result"
    if source == "imaging_rule":
        return "imaging_test"
    if source == "problem_rule":
        return str(features.get("rule") or "problem_head")
    if source == "dictionary":
        return "dictionary_alias"
    return None