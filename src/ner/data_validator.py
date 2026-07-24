from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.data_types import VALID_ENTITY_TYPES
from src.linking.terminology_normalizer import normalize_for_lookup


REQUIRED_SAMPLE_FIELDS = {
    "file_id", "text", "source", "confidence_tier", "generator_version", "seed", "entities",
}
REQUIRED_ENTITY_FIELDS = {"text", "start", "end", "type", "source", "metadata"}
REQUIRED_METADATA_FIELDS = {"template_family", "concept_family", "noise_profile"}
CONFIDENCE_TIERS = {
    "GOLD_VERIFIED", "TASK_ALIGNED_BY_CONSTRUCTION", "AUGMENTED_HIGH",
    "SILVER_HIGH", "REVIEW", "REJECT",
}
TRAINABLE_TIERS = {
    "GOLD_VERIFIED", "TASK_ALIGNED_BY_CONSTRUCTION", "AUGMENTED_HIGH", "SILVER_HIGH",
}
MARKER_RE = re.compile(r"\[\[/?E\d+\]\]|\{\{/?ENTITY[^}]*\}\}|</?ENT(?:ITY)?>", re.I)


@dataclass(slots=True)
class NERDataValidationReport:
    samples: int = 0
    entities: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    type_counts: Counter[str] = field(default_factory=Counter)
    source_counts: Counter[str] = field(default_factory=Counter)
    tier_counts: Counter[str] = field(default_factory=Counter)
    noise_counts: Counter[str] = field(default_factory=Counter)
    concept_family_counts: Counter[str] = field(default_factory=Counter)
    records: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "samples": self.samples,
            "entities": self.entities,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "type_counts": dict(sorted(self.type_counts.items())),
            "source_counts": dict(sorted(self.source_counts.items())),
            "confidence_tier_counts": dict(sorted(self.tier_counts.items())),
            "noise_profile_counts": dict(sorted(self.noise_counts.items())),
            "concept_family_counts": dict(sorted(self.concept_family_counts.items())),
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_ner_jsonl(path: str | Path, *, allow_overlaps: bool = False) -> NERDataValidationReport:
    report = NERDataValidationReport()
    seen_ids: set[str] = set()
    seen_text: dict[str, str] = {}
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            sample = json.loads(line)
        except json.JSONDecodeError as exc:
            _error(report, line_number, "invalid_json", str(exc))
            continue
        report.samples += 1
        if not isinstance(sample, dict):
            _error(report, line_number, "sample_not_object", "Sample must be an object")
            continue
        missing = REQUIRED_SAMPLE_FIELDS - set(sample)
        if missing:
            _error(report, line_number, "missing_sample_fields", sorted(missing))
            continue
        file_id, text, entities = sample["file_id"], sample["text"], sample["entities"]
        if not isinstance(file_id, str) or not file_id:
            _error(report, line_number, "invalid_file_id", file_id)
        elif file_id in seen_ids:
            _error(report, line_number, "duplicate_file_id", file_id)
        seen_ids.add(str(file_id))
        if not isinstance(text, str) or not isinstance(entities, list):
            _error(report, line_number, "invalid_text_or_entities", None)
            continue
        if not text.strip():
            _error(report, line_number, "empty_sample_text", file_id)
        if MARKER_RE.search(text):
            _error(report, line_number, "marker_leakage", file_id)
        normalized_text = _normalized_text(text)
        if normalized_text in seen_text:
            _error(report, line_number, "duplicate_normalized_text", {
                "file_id": file_id, "other_file_id": seen_text[normalized_text],
            })
        else:
            seen_text[normalized_text] = str(file_id)
        tier = sample.get("confidence_tier")
        if tier not in CONFIDENCE_TIERS:
            _error(report, line_number, "invalid_confidence_tier", tier)
        if not isinstance(sample.get("source"), str) or not sample["source"]:
            _error(report, line_number, "invalid_source", sample.get("source"))
        if not isinstance(sample.get("generator_version"), str) or not sample["generator_version"]:
            _error(report, line_number, "invalid_generator_version", sample.get("generator_version"))
        if not isinstance(sample.get("seed"), int):
            _error(report, line_number, "invalid_seed", sample.get("seed"))
        report.source_counts[str(sample.get("source", ""))] += 1
        report.tier_counts[str(tier)] += 1

        exact_keys: set[tuple[int, int, str]] = set()
        spans: list[tuple[int, int, str, int]] = []
        families: set[str] = set()
        original_ids: set[str] = set()
        for entity_index, entity in enumerate(entities):
            report.entities += 1
            valid = _validate_entity(report, line_number, entity_index, text, entity, exact_keys)
            if valid is None:
                continue
            start, end, entity_type, metadata = valid
            spans.append((start, end, entity_type, entity_index))
            report.type_counts[entity_type] += 1
            noise = str(metadata.get("noise_profile", ""))
            family = str(metadata.get("concept_family", ""))
            report.noise_counts[noise] += 1
            report.concept_family_counts[family] += 1
            families.add(family)
            if metadata.get("original_sample_id"):
                original_ids.add(str(metadata["original_sample_id"]))
            if tier == "AUGMENTED_HIGH":
                if not metadata.get("original_sample_id") or not metadata.get("transformations"):
                    _error(report, line_number, "missing_transformation_provenance", entity_index)
        if not allow_overlaps:
            _validate_overlaps(report, line_number, spans)
        report.records.append({
            "file_id": str(file_id), "text": text, "normalized_text": normalized_text,
            "text_hash": _text_hash(text), "source": str(sample.get("source", "")),
            "tier": str(tier), "families": sorted(families),
            "original_sample_ids": sorted(original_ids),
        })
    return report


def audit_dataset_bundle(
    *,
    train_paths: Sequence[str | Path],
    development_path: str | Path,
    calibration_path: str | Path,
    lockbox_text_paths: Iterable[str | Path] = (),
    near_duplicate_threshold: float = 0.96,
) -> dict[str, Any]:
    all_paths = [*train_paths, development_path, calibration_path]
    reports = {str(Path(path)): validate_ner_jsonl(path) for path in all_paths}
    errors: list[dict[str, Any]] = []
    for path, report in reports.items():
        if not report.ok:
            errors.append({"code": "dataset_validation_failed", "path": path, "count": len(report.errors)})

    train_records = [record for path in train_paths for record in reports[str(Path(path))].records]
    dev_records = reports[str(Path(development_path))].records
    calibration_records = reports[str(Path(calibration_path))].records
    eval_records = [*dev_records, *calibration_records]
    eval_by_normalized = {record["normalized_text"]: record for record in eval_records}
    train_seen: dict[str, str] = {}
    cross_train_duplicates: list[dict[str, str]] = []
    for record in train_records:
        previous = train_seen.get(record["normalized_text"])
        if previous:
            cross_train_duplicates.append({"file_id": record["file_id"], "other_file_id": previous})
        else:
            train_seen[record["normalized_text"]] = record["file_id"]
        other = eval_by_normalized.get(record["normalized_text"])
        if other:
            errors.append({
                "code": "train_eval_text_leakage", "train_file_id": record["file_id"],
                "eval_file_id": other["file_id"],
            })
    if cross_train_duplicates:
        errors.append({"code": "cross_train_duplicate", "count": len(cross_train_duplicates)})

    cross_split_near_duplicates: list[dict[str, Any]] = []
    for train in train_records:
        for other in eval_records:
            ratio = SequenceMatcher(None, train["normalized_text"], other["normalized_text"]).ratio()
            if ratio >= near_duplicate_threshold:
                cross_split_near_duplicates.append({
                    "train_file_id": train["file_id"], "eval_file_id": other["file_id"],
                    "ratio": round(ratio, 6),
                })
    if cross_split_near_duplicates:
        errors.append({"code": "cross_split_near_duplicate", "count": len(cross_split_near_duplicates)})

    group_splits: dict[str, set[str]] = {}
    for split, records in (("train", train_records), ("development", dev_records), ("calibration", calibration_records)):
        for record in records:
            for group in [*record["original_sample_ids"], *record["families"]]:
                if group:
                    group_splits.setdefault(group, set()).add(split)
    group_leakage = {key: sorted(value) for key, value in group_splits.items() if len(value) > 1}
    if group_leakage:
        errors.append({"code": "group_split_leakage", "count": len(group_leakage)})

    lockbox_hashes = {_text_hash(Path(path).read_text(encoding="utf-8")) for path in lockbox_text_paths}
    lockbox_matches = [record["file_id"] for record in train_records if record["text_hash"] in lockbox_hashes]
    if lockbox_matches:
        errors.append({"code": "lockbox_text_leakage", "file_ids": lockbox_matches})

    return {
        "ok": not errors,
        "errors": errors,
        "datasets": {path: report.to_dict() for path, report in reports.items()},
        "cross_split_near_duplicates": cross_split_near_duplicates,
        "cross_train_duplicates": cross_train_duplicates,
        "group_leakage": group_leakage,
        "lockbox_hash_count": len(lockbox_hashes),
        "lockbox_match_count": len(lockbox_matches),
    }


def _validate_entity(report, line_number, entity_index, text, entity, exact_keys):
    if not isinstance(entity, dict):
        _error(report, line_number, "entity_not_object", entity_index)
        return None
    missing = REQUIRED_ENTITY_FIELDS - set(entity)
    if missing:
        _error(report, line_number, "missing_entity_fields", {"index": entity_index, "fields": sorted(missing)})
        return None
    try:
        start, end = int(entity["start"]), int(entity["end"])
    except (TypeError, ValueError):
        _error(report, line_number, "invalid_offset", entity_index)
        return None
    entity_type = unicodedata.normalize("NFC", str(entity["type"]))
    if entity_type not in VALID_ENTITY_TYPES:
        _error(report, line_number, "invalid_type", {"index": entity_index, "type": entity_type})
    entity_text = entity.get("text")
    if not isinstance(entity_text, str) or not entity_text.strip():
        _error(report, line_number, "empty_entity_text", entity_index)
    if start < 0 or end <= start or end > len(text) or text[start:end] != entity_text:
        _error(report, line_number, "offset_mismatch", {
            "index": entity_index, "position": [start, end], "entity_text": entity_text,
        })
    if isinstance(entity_text, str) and MARKER_RE.search(entity_text):
        _error(report, line_number, "marker_leakage", entity_index)
    key = (start, end, entity_type)
    if key in exact_keys:
        _error(report, line_number, "duplicate_exact_entity", {"index": entity_index, "key": key})
    exact_keys.add(key)
    metadata = entity["metadata"]
    if not isinstance(metadata, dict) or REQUIRED_METADATA_FIELDS - set(metadata):
        _error(report, line_number, "invalid_metadata", {
            "index": entity_index, "required": sorted(REQUIRED_METADATA_FIELDS),
        })
        metadata = {}
    if not isinstance(entity.get("source"), str) or not entity["source"]:
        _error(report, line_number, "invalid_entity_source", entity_index)
    return start, end, entity_type, metadata


def _validate_overlaps(report, line_number: int, spans: Sequence[tuple[int, int, str, int]]) -> None:
    ordered = sorted(spans)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            if second[0] >= first[1]:
                break
            if max(first[0], second[0]) < min(first[1], second[1]):
                _error(report, line_number, "overlapping_entities", {
                    "first_index": first[3], "second_index": second[3],
                    "first": [first[0], first[1], first[2]],
                    "second": [second[0], second[1], second[2]],
                })


def _normalized_text(text: str) -> str:
    return normalize_for_lookup(unicodedata.normalize("NFC", text))


def _text_hash(text: str) -> str:
    return hashlib.sha256(_normalized_text(text).encode("utf-8")).hexdigest()


def _error(report: NERDataValidationReport, line: int, code: str, value: Any) -> None:
    report.errors.append({"line": line, "code": code, "value": value})