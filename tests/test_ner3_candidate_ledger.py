from __future__ import annotations

import pytest

from src.data_types import SpanCandidate
from src.ner.candidate_ledger import read_candidate_ledger, write_candidate_ledger
from src.ner.evidence_adapter import normalize_candidates


IDENTITY = {"config_hash": "cfg-a", "model_hash": "model-a", "selected_config_hash": "selected-a"}


def _gliner(raw: str, start: int, end: int) -> SpanCandidate:
    return SpanCandidate(
        raw[start:end], start, end, "TRIỆU_CHỨNG", "gliner", .8,
        features={"pass_name": "full", "prompt_label": "symptom", "raw_model_score": .8, "window_id": "w0"},
    )


def test_ledger_round_trip_is_byte_deterministic_and_raw_aligned(tmp_path) -> None:
    raw = "Sốt\r\nđau ngực"
    chest_start = raw.index("đau ngực")
    candidates = normalize_candidates([
        _gliner(raw, chest_start, len(raw)),
        SpanCandidate("Sốt", 0, 3, "TRIỆU_CHỨNG", "problem_rule", .76),
    ])
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_candidate_ledger(first, file_id="1", raw_text=raw, candidates=candidates, metadata=IDENTITY)
    write_candidate_ledger(second, file_id="1", raw_text=raw, candidates=list(reversed(candidates)), metadata=IDENTITY)
    assert first.read_bytes() == second.read_bytes()
    payload, restored = read_candidate_ledger(first, raw)
    assert payload["file_id"] == "1"
    assert payload["validation"]["evidence_error_count"] == 0
    assert payload["source_candidate_counts"] == {"gliner": 1, "problem_rule": 1}
    assert [row.text for row in restored] == ["Sốt", "đau ngực"]


def test_ledger_rejects_changed_input_and_bad_offset(tmp_path) -> None:
    raw = "sốt"
    path = tmp_path / "ledger.json"
    write_candidate_ledger(path, file_id="1", raw_text=raw, candidates=normalize_candidates([_gliner(raw, 0, 3)]), metadata=IDENTITY)
    with pytest.raises(ValueError, match="input hash"):
        read_candidate_ledger(path, "ho")
    with pytest.raises(ValueError, match="offset"):
        write_candidate_ledger(tmp_path / "bad.json", file_id="1", raw_text=raw, candidates=[SpanCandidate("ho", 0, 2, "TRIỆU_CHỨNG", "gliner", .8)], metadata=IDENTITY)


def test_ledger_rejects_config_or_model_identity_change(tmp_path) -> None:
    raw = "sốt"
    path = tmp_path / "ledger.json"
    candidates = normalize_candidates([_gliner(raw, 0, 3)])
    metadata = IDENTITY
    write_candidate_ledger(path, file_id="1", raw_text=raw, candidates=candidates, metadata=metadata)
    read_candidate_ledger(path, raw, expected_metadata=metadata)
    with pytest.raises(ValueError, match="config_hash"):
        read_candidate_ledger(path, raw, expected_metadata={"config_hash": "cfg-b"})