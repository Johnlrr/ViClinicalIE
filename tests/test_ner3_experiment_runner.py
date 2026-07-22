from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.review_ner3_source_errors import build_review_rows
from scripts.run_ner3_experiments import (
    _assert_development_only,
    _assert_prerequisites,
    run_checkpoint,
    validate_checkpoint_plan,
    validate_ledgers,
)
from scripts.summarize_ner3_experiments import summarize
from src.config import load_config, load_yaml
from src.data_types import SpanCandidate
from src.io_utils import write_json
from src.ner.candidate_ledger import write_candidate_ledger
from src.ner.evidence_adapter import normalize_candidates


class _FakeDownstream:
    def __init__(self, formatter) -> None:
        self.formatter = formatter

    def process_resolved_end_to_end(self, raw_text, entities, *, file_id=""):
        return SimpleNamespace(records=self.formatter.format_entities(entities))


def test_approved_matrix_is_exact_abcd_and_config_loads() -> None:
    rows = validate_checkpoint_plan(load_yaml("configs/ner3/experiment_matrix.yaml"))
    assert [(row["id"], row["mode"]) for row in rows] == [
        ("A", "v1"), ("B", "gliner"), ("C", "naive_union"), ("D", "simple_fusion"),
    ]
    config = load_config("configs/ner3/base.yaml")
    assert config.raw["extractors"]["gliner"]["enabled"] is True
    assert all(config.raw["extractors"][name]["enabled"] for name in ("dictionary", "drug", "lab", "imaging", "problem"))
    assert config.raw["ner3"]["fusion"]["structured_anchors_enabled"] is True


def test_development_only_and_checkpoint_dependencies(tmp_path: Path) -> None:
    policy = load_yaml("configs/ner3/selection_policy.yaml")
    _assert_development_only("development", policy)
    with pytest.raises(PermissionError, match="development-only"):
        _assert_development_only("calibration", policy)
    with pytest.raises(PermissionError, match="requires completed"):
        _assert_prerequisites({"id": "C", "requires": ["A", "B"]}, tmp_path, set())
    for checkpoint in ("A", "B"):
        write_json(tmp_path / checkpoint / "run_manifest.json", {})
    _assert_prerequisites({"id": "C", "requires": ["A", "B"]}, tmp_path, set())


def test_replays_one_ledger_through_all_checkpoints_without_a_model(tmp_path: Path) -> None:
    raw = "aspirin và sốt"
    file_id = "1"
    inputs, gold, ledgers = tmp_path / "input", tmp_path / "gold", tmp_path / "ledgers"
    inputs.mkdir(); gold.mkdir()
    (inputs / "1.txt").write_text(raw, encoding="utf-8")
    write_json(gold / "1.json", [
        {"text": "aspirin", "position": [0, 7], "type": "THUỐC", "assertions": [], "candidates": []},
        {"text": "sốt", "position": [11, 14], "type": "TRIỆU_CHỨNG", "assertions": []},
    ])
    candidates = [
        SpanCandidate("aspirin", 0, 7, "THUỐC", "drug_rule", .9),
        SpanCandidate("aspirin", 0, 7, "THUỐC", "gliner", .8, features={"window_id": "w0", "pass_name": "full", "prompt_label": "drug"}),
        SpanCandidate("sốt", 11, 14, "TRIỆU_CHỨNG", "gliner", .8, features={"window_id": "w0", "pass_name": "full", "prompt_label": "symptom"}),
    ]
    metadata = {"config_hash": "cfg", "model_hash": "model", "selected_config_hash": "selected"}
    write_candidate_ledger(ledgers / "1.json", file_id=file_id, raw_text=raw, candidates=normalize_candidates(candidates), metadata=metadata)
    ledger_manifest = validate_ledgers([file_id], inputs, ledgers)
    config = SimpleNamespace(
        config_path=Path("configs/ner3/base.yaml"),
        raw={
            "output_format": {}, "evaluation": {}, "prediction_validation": {},
            "type_resolution": {"source_priority": {"drug_rule": 85, "gliner": 50}},
            "ner3": {"fusion": {"structured_anchors_enabled": True}},
        },
    )
    matrix, policy = Path("configs/ner3/experiment_matrix.yaml"), Path("configs/ner3/selection_policy.yaml")
    from src.formatting import PredictionFormatter
    downstream = _FakeDownstream(PredictionFormatter())
    manifests = []
    for checkpoint, mode in (("A", "v1"), ("B", "gliner"), ("C", "naive_union"), ("D", "simple_fusion")):
        manifests.append(run_checkpoint(
            spec={"id": checkpoint, "name": checkpoint, "mode": mode, "requires": [], "diagnostic_only": checkpoint == "C"},
            config=config, ids=[file_id], input_dir=inputs, gold_dir=gold,
            selected_input=inputs, selected_gold=gold, ledger_dir=ledgers,
            output_root=tmp_path / "runs", ledger_manifest=ledger_manifest,
            matrix_path=matrix, policy_path=policy,
            downstream_pipeline=downstream,
        ))
    assert {manifest["ledger_manifest_hash"] for manifest in manifests} == {ledger_manifest["manifest_hash"]}
    assert manifests[2]["duplicate_exact_span_count"] == 0
    assert manifests[3]["gliner_unconfirmed"] == {"total": 1, "survived_exact": 1}
    assert manifests[3]["official_like_final_score"] >= 0.0
    assert manifests[0]["density"]["density_ratio"] == 1.0
    assert manifests[3]["density"]["density_ratio"] == pytest.approx(2.0)
    assert (tmp_path / "runs/D/predictions/end_to_end/1.json").is_file()
    summary = summarize(manifests, load_yaml(policy))
    assert summary["safety_gates_pass"] is False
    assert summary["full_development_complete"] is False
    assert summary["review_ready"] is False
    assert summary["promotion_decision"] == "blocked"
    assert summary["automatic_promotion"] is False


def test_source_error_reviewer_uses_recorded_ledger_sources(tmp_path: Path) -> None:
    root = tmp_path / "ner3"
    raw = "sốt"
    (root / "corpus/input").mkdir(parents=True)
    (root / "corpus/input/1.txt").write_text(raw, encoding="utf-8")
    write_candidate_ledger(
        root / "candidate_ledgers/1.json", file_id="1", raw_text=raw,
        candidates=normalize_candidates([SpanCandidate(raw, 0, 3, "TRIỆU_CHỨNG", "gliner", .8, features={"window_id": "w0", "pass_name": "full", "prompt_label": "symptom"})]),
        metadata={"config_hash": "cfg", "model_hash": "model", "selected_config_hash": "selected"},
    )
    evaluation = root / "B/evaluation"
    evaluation.mkdir(parents=True)
    (evaluation / "false_positives.jsonl").write_text(
        json.dumps({"file_id": "1", "text": raw, "position": [0, 3], "type": "TRIỆU_CHỨNG"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rows, counts = build_review_rows(root, checkpoints=("B",))
    assert rows[0]["sources"] == ["gliner"]
    assert counts["B"]["gliner"]["TRIỆU_CHỨNG"]["false_positive"] == 1


def test_summarizer_rejects_mixed_ledgers() -> None:
    manifests = []
    for checkpoint, mode in (("A", "v1"), ("B", "gliner"), ("C", "naive_union"), ("D", "simple_fusion")):
        manifests.append({
            "checkpoint": checkpoint, "mode": mode, "ledger_manifest_hash": checkpoint,
            "metrics": {"exact": {}, "relaxed": {}}, "validation_error_count": 0,
            "ledger_evidence_error_count": 0, "duplicate_exact_span_count": 0,
            "density": {"density_ratio": 1.0},
            "gliner_unconfirmed": {"total": 0, "survived_exact": 0},
        })
    summary = summarize(manifests, load_yaml("configs/ner3/selection_policy.yaml"))
    assert summary["shared_candidate_ledger"] is False
    assert summary["promotion_decision"] == "blocked"