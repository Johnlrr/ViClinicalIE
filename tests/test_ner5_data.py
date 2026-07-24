from __future__ import annotations

import json
from pathlib import Path

from scripts.build_ner5_data import build_ner5_bundle
from src.config import load_yaml
from src.ner.data_validator import audit_dataset_bundle, validate_ner_jsonl
from src.ner.task_aligned_generator import (
    dataset_hash,
    generate_noisy_samples,
    generate_task_aligned_samples,
)


INVENTORY = {
    "TRIỆU_CHỨNG": [{"surface": "đau ngực", "concept_id": "symptom:1"}],
    "CHẨN_ĐOÁN": [{"surface": "viêm phổi", "concept_id": "J18"}],
    "THUỐC": [{"surface": "metoprolol", "concept_id": "6918"}],
    "TÊN_XÉT_NGHIỆM": [{"surface": "CRP", "concept_id": "crp"}],
}


def write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_generator_is_deterministic_offset_safe_and_covers_five_types() -> None:
    first = generate_task_aligned_samples(INVENTORY, seed=42)
    second = generate_task_aligned_samples(INVENTORY, seed=42)
    assert dataset_hash(first) == dataset_hash(second)
    noisy = generate_noisy_samples(first, seed=42)
    types = {entity["type"] for sample in first for entity in sample["entities"]}
    assert len(types) == 5
    for sample in [*first, *noisy]:
        assert "[[E" not in sample["text"]
        for entity in sample["entities"]:
            assert sample["text"][entity["start"]:entity["end"]] == entity["text"]
    assert all(sample["confidence_tier"] == "AUGMENTED_HIGH" for sample in noisy)
    assert all(
        entity["metadata"].get("original_sample_id") and entity["metadata"].get("transformations")
        for sample in noisy for entity in sample["entities"]
    )


def test_validator_detects_marker_overlap_duplicate_and_bad_tier(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    sample = {
        "file_id": "x", "text": "[[E0]]đau ngực[[/E0]]", "source": "test",
        "confidence_tier": "UNKNOWN", "generator_version": "1", "seed": 1,
        "entities": [
            {
                "text": "đau ngực", "start": 6, "end": 14, "type": "TRIỆU_CHỨNG",
                "source": "test", "metadata": {
                    "template_family": "t", "concept_family": "c", "noise_profile": "clean",
                },
            },
            {
                "text": "đau", "start": 6, "end": 10, "type": "TRIỆU_CHỨNG",
                "source": "test", "metadata": {
                    "template_family": "t", "concept_family": "c2", "noise_profile": "clean",
                },
            },
        ],
    }
    write_jsonl(path, [sample, sample])
    report = validate_ner_jsonl(path)
    codes = {error["code"] for error in report.errors}
    assert {"marker_leakage", "invalid_confidence_tier", "overlapping_entities", "duplicate_file_id"} <= codes


def test_bundle_audit_detects_train_eval_and_lockbox_leakage(tmp_path: Path) -> None:
    clean = generate_task_aligned_samples(INVENTORY, seed=42)[0]
    train = tmp_path / "train.jsonl"
    dev = tmp_path / "dev.jsonl"
    calibration = tmp_path / "calibration.jsonl"
    write_jsonl(train, [clean])
    leaked = dict(clean, file_id="development_1", source="competition_gold", confidence_tier="GOLD_VERIFIED")
    write_jsonl(dev, [leaked])
    other = dict(clean, file_id="calibration_1", text="Nội dung hoàn toàn khác.", entities=[])
    write_jsonl(calibration, [other])
    lockbox = tmp_path / "lockbox.txt"
    lockbox.write_text(clean["text"], encoding="utf-8")
    audit = audit_dataset_bundle(
        train_paths=[train], development_path=dev, calibration_path=calibration,
        lockbox_text_paths=[lockbox],
    )
    codes = {error["code"] for error in audit["errors"]}
    assert "train_eval_text_leakage" in codes
    assert "lockbox_text_leakage" in codes


def test_real_bundle_passes_technical_gate_but_requires_human_review(tmp_path: Path) -> None:
    config_path = Path("configs/ner5.yaml").resolve()
    config = load_yaml(config_path)
    manifest = build_ner5_bundle(config, output_dir=tmp_path / "ner_v2", config_path=config_path)
    assert manifest["technical_gate_pass"] is True
    assert manifest["data_ready"] is False
    assert manifest["human_review"]["status"] == "pending"
    assert manifest["label_mapping"]["Symptom_and_Disease"] == "UNMAPPED_REVIEW"
    assert manifest["conversion"]["lockbox_exported"] is False
    assert manifest["validation"]["lockbox_match_count"] == 0
    assert set(manifest["train_type_counts"]) == {
        "TRIỆU_CHỨNG", "CHẨN_ĐOÁN", "THUỐC", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM",
    }