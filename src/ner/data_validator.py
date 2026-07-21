from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.data_types import VALID_ENTITY_TYPES


REQUIRED_SAMPLE_FIELDS = {"file_id", "text", "source", "generator_version", "seed", "entities"}
REQUIRED_ENTITY_FIELDS = {"text", "start", "end", "type", "source", "metadata"}
REQUIRED_METADATA_FIELDS = {"template_family", "concept_family", "noise_profile"}


@dataclass(slots=True)
class NERDataValidationReport:
    samples: int = 0
    entities: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "samples": self.samples, "entities": self.entities, "error_count": len(self.errors), "errors": self.errors}


def validate_ner_jsonl(path: str | Path) -> NERDataValidationReport:
    report = NERDataValidationReport()
    seen_ids: set[str] = set()
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
        exact_keys: set[tuple[int, int, str]] = set()
        for entity_index, entity in enumerate(entities):
            report.entities += 1
            _validate_entity(report, line_number, entity_index, text, entity, exact_keys)
    return report


def _validate_entity(report, line_number, entity_index, text, entity, exact_keys) -> None:
    if not isinstance(entity, dict):
        _error(report, line_number, "entity_not_object", entity_index)
        return
    missing = REQUIRED_ENTITY_FIELDS - set(entity)
    if missing:
        _error(report, line_number, "missing_entity_fields", {"index": entity_index, "fields": sorted(missing)})
        return
    try:
        start, end = int(entity["start"]), int(entity["end"])
    except (TypeError, ValueError):
        _error(report, line_number, "invalid_offset", entity_index)
        return
    entity_type = entity["type"]
    if entity_type not in VALID_ENTITY_TYPES:
        _error(report, line_number, "invalid_type", {"index": entity_index, "type": entity_type})
    if start < 0 or end <= start or end > len(text) or text[start:end] != entity["text"]:
        _error(report, line_number, "offset_mismatch", {"index": entity_index, "position": [start, end], "entity_text": entity["text"]})
    key = (start, end, str(entity_type))
    if key in exact_keys:
        _error(report, line_number, "duplicate_exact_entity", {"index": entity_index, "key": key})
    exact_keys.add(key)
    metadata = entity["metadata"]
    if not isinstance(metadata, dict) or REQUIRED_METADATA_FIELDS - set(metadata):
        _error(report, line_number, "invalid_metadata", {"index": entity_index, "required": sorted(REQUIRED_METADATA_FIELDS)})


def _error(report: NERDataValidationReport, line: int, code: str, value: Any) -> None:
    report.errors.append({"line": line, "code": code, "value": value})