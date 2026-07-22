from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from src.data_types import SpanCandidate
from src.ner.evidence_adapter import validate_candidate_evidence


LEDGER_SCHEMA_VERSION = "ner3-candidate-ledger-v1"


def write_candidate_ledger(
    path: str | Path, *, file_id: str, raw_text: str,
    candidates: list[SpanCandidate], metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = sorted(candidates, key=_candidate_sort_key)
    evidence_errors: list[dict[str, Any]] = []
    for candidate in ordered:
        if raw_text[candidate.start:candidate.end] != candidate.text:
            raise ValueError(f"Candidate offset mismatch: {candidate.start}-{candidate.end}")
        errors = validate_candidate_evidence(candidate)
        if errors:
            evidence_errors.append({"position": [candidate.start, candidate.end], "source": candidate.source, "errors": errors})
    if evidence_errors:
        raise ValueError(f"Candidate evidence validation failed: {evidence_errors[:3]}")
    required_identity = {"config_hash", "model_hash", "selected_config_hash"}
    missing_identity = sorted(required_identity - set(metadata or {}))
    if missing_identity:
        raise ValueError(f"Candidate ledger missing identity metadata: {missing_identity}")
    source_counts = Counter(candidate.source for candidate in ordered)
    payload = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "file_id": str(file_id),
        "input_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "metadata": dict(metadata or {}),
        "candidate_count": len(ordered),
        "source_candidate_counts": dict(sorted(source_counts.items())),
        "validation": {
            "offset_errors": 0,
            "evidence_errors": evidence_errors,
            "evidence_error_count": len(evidence_errors),
        },
        "candidates": [_to_row(candidate) for candidate in ordered],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return payload


def read_candidate_ledger(
    path: str | Path,
    raw_text: str,
    *,
    expected_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[SpanCandidate]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ValueError("Unsupported candidate ledger schema")
    input_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    if payload.get("input_hash") != input_hash:
        raise ValueError("Candidate ledger input hash mismatch")
    actual_metadata = payload.get("metadata", {})
    for key, expected in dict(expected_metadata or {}).items():
        if actual_metadata.get(key) != expected:
            raise ValueError(f"Candidate ledger metadata mismatch: {key}")
    candidates = [_from_row(row, raw_text) for row in payload.get("candidates", [])]
    if len(candidates) != int(payload.get("candidate_count", -1)):
        raise ValueError("Candidate ledger candidate count mismatch")
    if candidates != sorted(candidates, key=_candidate_sort_key):
        raise ValueError("Candidate ledger order mismatch")
    source_counts = dict(sorted(Counter(candidate.source for candidate in candidates).items()))
    if payload.get("source_candidate_counts") != source_counts:
        raise ValueError("Candidate ledger source count mismatch")
    evidence_errors = [
        error for candidate in candidates for error in validate_candidate_evidence(candidate)
    ]
    if evidence_errors or payload.get("validation", {}).get("evidence_error_count") != 0:
        raise ValueError("Candidate ledger evidence validation failed")
    return payload, candidates


def candidate_ledger_bytes(
    *, file_id: str, raw_text: str, candidates: list[SpanCandidate], metadata: Mapping[str, Any] | None = None,
) -> bytes:
    """Return canonical ledger bytes without touching the filesystem."""
    ordered = sorted(candidates, key=_candidate_sort_key)
    for candidate in ordered:
        if raw_text[candidate.start:candidate.end] != candidate.text:
            raise ValueError(f"Candidate offset mismatch: {candidate.start}-{candidate.end}")
    source_counts = Counter(candidate.source for candidate in ordered)
    evidence_errors = [
        {"position": [candidate.start, candidate.end], "source": candidate.source, "errors": errors}
        for candidate in ordered if (errors := validate_candidate_evidence(candidate))
    ]
    payload = {
        "schema_version": LEDGER_SCHEMA_VERSION, "file_id": str(file_id),
        "input_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "metadata": dict(metadata or {}), "candidate_count": len(ordered),
        "source_candidate_counts": dict(sorted(source_counts.items())),
        "validation": {"offset_errors": 0, "evidence_errors": evidence_errors, "evidence_error_count": len(evidence_errors)},
        "candidates": [_to_row(candidate) for candidate in ordered],
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _to_row(candidate: SpanCandidate) -> dict[str, Any]:
    return {
        "text": candidate.text, "start": candidate.start, "end": candidate.end,
        "raw_type": candidate.raw_type, "source": candidate.source, "score": candidate.score,
        "section": candidate.section, "subsection": candidate.subsection,
        "context_left": candidate.context_left, "context_right": candidate.context_right,
        "features": candidate.features,
    }


def _from_row(row: Mapping[str, Any], raw_text: str) -> SpanCandidate:
    start, end = int(row["start"]), int(row["end"])
    if raw_text[start:end] != row.get("text"):
        raise ValueError("Candidate ledger offset mismatch")
    return SpanCandidate(
        text=str(row["text"]), start=start, end=end, raw_type=row.get("raw_type"),
        source=str(row["source"]), score=float(row["score"]), section=row.get("section"),
        subsection=row.get("subsection"), context_left=str(row.get("context_left", "")),
        context_right=str(row.get("context_right", "")), features=dict(row.get("features", {})),
    )


def _candidate_sort_key(item: SpanCandidate) -> tuple[Any, ...]:
    feature_key = json.dumps(item.features, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        item.start, item.end, item.source, item.raw_type or "", -item.score, item.text,
        item.section or "", item.subsection or "", item.context_left, item.context_right, feature_key,
    )