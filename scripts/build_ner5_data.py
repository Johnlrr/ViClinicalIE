from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_yaml
from src.io_utils import write_json
from src.ner.data_validator import audit_dataset_bundle
from src.ner.task_aligned_generator import (
    GENERATOR_VERSION,
    convert_gold_split,
    dataset_hash,
    generate_noisy_samples,
    generate_task_aligned_samples,
    load_concept_inventory,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and validate the deterministic NER-5 data bundle.")
    parser.add_argument("--config", default="configs/ner5.yaml")
    parser.add_argument("--output-dir", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = _resolve(args.config)
    config = load_yaml(config_path)
    output_dir = _resolve(args.output_dir or str(config["output_dir"]))
    result = build_ner5_bundle(config, output_dir=output_dir, config_path=config_path)
    print(json.dumps({
        "data_ready": result["data_ready"],
        "technical_gate_pass": result["technical_gate_pass"],
        "human_review_status": result["human_review"]["status"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False))
    return 0 if result["technical_gate_pass"] else 1


def build_ner5_bundle(config: Mapping[str, Any], *, output_dir: Path, config_path: Path) -> dict[str, Any]:
    seed = int(config.get("seed", 42))
    splits = load_yaml(_resolve(str(config["splits_config"])))
    input_dir = _resolve(str(config["gold_input_dir"]))
    gold_dir = _resolve(str(config["gold_dir"]))
    inventory = load_concept_inventory(config, PROJECT_ROOT)

    clean = generate_task_aligned_samples(inventory, seed=seed)
    noisy = generate_noisy_samples(clean, seed=seed)
    development, dev_conversion = convert_gold_split(
        input_dir=input_dir, gold_dir=gold_dir,
        ids=splits["development"]["ids"], split="development", seed=seed,
    )
    calibration, calibration_conversion = convert_gold_split(
        input_dir=input_dir, gold_dir=gold_dir,
        ids=splits["calibration"]["ids"], split="calibration", seed=seed,
    )

    # In-memory rebuild proves generation itself is deterministic before writing.
    deterministic = (
        dataset_hash(clean) == dataset_hash(generate_task_aligned_samples(inventory, seed=seed))
        and dataset_hash(noisy) == dataset_hash(generate_noisy_samples(clean, seed=seed))
    )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "task_aligned_train": output_dir / "task_aligned_train.jsonl",
        "noisy_train": output_dir / "noisy_train.jsonl",
        "development": output_dir / "development.jsonl",
        "calibration": output_dir / "calibration.jsonl",
    }
    for key, rows in (
        ("task_aligned_train", clean), ("noisy_train", noisy),
        ("development", development), ("calibration", calibration),
    ):
        _write_jsonl(paths[key], rows)

    lockbox_paths = [input_dir / f"{value}.txt" for value in splits["lockbox"]["ids"]]
    validation = audit_dataset_bundle(
        train_paths=[paths["task_aligned_train"], paths["noisy_train"]],
        development_path=paths["development"], calibration_path=paths["calibration"],
        lockbox_text_paths=lockbox_paths,
        near_duplicate_threshold=float(config.get("validation", {}).get("near_duplicate_threshold", 0.96)),
    )
    validation["datasets"] = {
        Path(path).name: report for path, report in validation["datasets"].items()
    }
    train_type_counts = Counter(
        entity["type"] for sample in [*clean, *noisy] for entity in sample.get("entities", [])
    )
    five_type_coverage = len(train_type_counts) == 5
    technical_gate = bool(validation["ok"] and deterministic and five_type_coverage)
    review = dict(config.get("human_review", {}))
    review_approved = review.get("status") == "approved" and bool(review.get("reviewer")) and bool(review.get("date"))

    source_inventory = [
        _local_source("symptoms", _resolve(str(config["sources"]["symptoms"])), "project dictionary", True),
        _local_source("labs", _resolve(str(config["sources"]["labs"])), "project dictionary", True),
        _local_source("diagnosis manual aliases", _resolve(str(config["sources"]["diagnosis_manual"])), "project curated dictionary", True),
        _local_source("ICD-10 aliases", _resolve(str(config["sources"]["diagnosis"])), "local processed terminology snapshot", True),
        _local_source("drug manual aliases", _resolve(str(config["sources"]["drugs_manual"])), "project curated dictionary", True),
        _local_source("RxNorm aliases", _resolve(str(config["sources"]["drugs"])), "local processed terminology snapshot", True),
        *[dict(row) for row in config.get("external_sources", [])],
    ]
    manifest = {
        "schema_version": "ner5-manifest-v1",
        "generator_version": GENERATOR_VERSION,
        "annotation_guideline_version": config["annotation_guideline_version"],
        "data_schema_version": config["schema_version"],
        "seed": seed,
        "config_hash": _sha256(config_path),
        "technical_gate_pass": technical_gate,
        "data_ready": bool(technical_gate and review_approved),
        "human_review": {
            **review,
            "pilot_sample_ids": _pilot_sample_ids(clean, noisy),
            "required_checks": [
                "boundary_and_type", "positive_and_hard_negative",
                "clean_and_each_noise_profile", "ontology_surface_plausibility",
            ],
        },
        "deterministic_rebuild": deterministic,
        "five_type_train_coverage": five_type_coverage,
        "train_type_counts": dict(sorted(train_type_counts.items())),
        "datasets": {
            key: {
                "path": path.name, "sha256": _sha256(path),
                "samples": _line_count(path), "bytes": path.stat().st_size,
            } for key, path in paths.items()
        },
        "conversion": {
            "development": dev_conversion,
            "calibration": calibration_conversion,
            "lockbox_exported": False,
        },
        "validation": validation,
        "source_inventory": source_inventory,
        "label_mapping": {
            "target_labels": sorted(train_type_counts),
            "Symptom_and_Disease": "UNMAPPED_REVIEW",
            "unknown_external_label": "UNMAPPED_REVIEW",
        },
        "confidence_tiers": {
            "task_aligned_train": "TASK_ALIGNED_BY_CONSTRUCTION",
            "noisy_train": "AUGMENTED_HIGH",
            "development": "GOLD_VERIFIED",
            "calibration": "GOLD_VERIFIED",
            "external_default": "REVIEW",
        },
        "ner6_recommendation": "eligible_for_go_no_go" if technical_gate and review_approved else "blocked_pending_human_review",
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _local_source(name: str, path: Path, usage: str, included: bool) -> dict[str, Any]:
    return {
        "name": name, "path": str(path.relative_to(PROJECT_ROOT)), "version": "local_snapshot",
        "sha256": _sha256(path), "usage_note": usage,
        "license_status": "project_provided_verify_redistribution", "included_in_training": included,
    }


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _pilot_sample_ids(clean: Sequence[Mapping[str, Any]], noisy: Sequence[Mapping[str, Any]]) -> list[str]:
    selected: list[str] = []
    seen_types: set[str] = set()
    for sample in clean:
        types = {str(entity["type"]) for entity in sample.get("entities", [])}
        if not types and not any(value.startswith("clean_negative") for value in selected):
            selected.append(str(sample["file_id"]))
        for entity_type in sorted(types - seen_types):
            selected.append(str(sample["file_id"]))
            seen_types.add(entity_type)
    seen_noise: set[str] = set()
    for sample in noisy:
        profiles = {
            str(entity.get("metadata", {}).get("noise_profile", ""))
            for entity in sample.get("entities", [])
        } - {""}
        for profile in sorted(profiles - seen_noise):
            selected.append(str(sample["file_id"]))
            seen_noise.add(profile)
    return list(dict.fromkeys(selected))


if __name__ == "__main__":
    raise SystemExit(main())