"""Validation helpers for V0 submission artifacts."""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from src.assertion import ALLOWED_ASSERTIONS
from src.models import ClinicalDocument
from src.output_writer import MAPPING_TYPES
from src.rule_extractors import ENTITY_LAB_NAME, ENTITY_LAB_RESULT, TARGET_ENTITY_TYPES


LAB_TYPES = {ENTITY_LAB_NAME, ENTITY_LAB_RESULT}


@dataclass
class ValidationReport:
    """Structured validation result for V0 artifacts."""

    ok: bool = True
    total_entities: int = 0
    by_type: Counter = field(default_factory=Counter)
    by_assertion: Counter = field(default_factory=Counter)
    empty_files: List[str] = field(default_factory=list)
    schema_errors: List[str] = field(default_factory=list)
    offset_errors: List[str] = field(default_factory=list)
    duplicate_errors: List[str] = field(default_factory=list)
    overlap_errors: List[str] = field(default_factory=list)
    zip_errors: List[str] = field(default_factory=list)

    def mark_error(self, bucket: List[str], message: str) -> None:
        """Record a validation error and mark report as failed."""
        bucket.append(message)
        self.ok = False


def _numeric_file_id(file_id: str) -> int:
    """Sort numeric file ids while keeping type check localized."""
    return int(file_id)


def _entity_identity(file_id: str, entity: Dict[str, object]) -> Tuple[object, ...]:
    """Exact duplicate identity for a final entity."""
    return (
        file_id,
        entity.get("text"),
        tuple(entity.get("position", [])) if isinstance(entity.get("position"), list) else entity.get("position"),
        entity.get("type"),
        tuple(entity.get("assertions", [])) if isinstance(entity.get("assertions"), list) else entity.get("assertions"),
        tuple(entity.get("candidates", [])) if isinstance(entity.get("candidates"), list) else entity.get("candidates"),
    )


def _validate_schema(file_id: str, index: int, entity: object, report: ValidationReport) -> bool:
    """Validate one entity's JSON schema."""
    prefix = f"{file_id}.json[{index}]"
    if not isinstance(entity, dict):
        report.mark_error(report.schema_errors, f"{prefix}: entity is not an object")
        return False

    required = {"text", "position", "type", "assertions"}
    missing = required - set(entity)
    if missing:
        report.mark_error(report.schema_errors, f"{prefix}: missing fields {sorted(missing)}")
        return False

    if not isinstance(entity["text"], str) or not entity["text"]:
        report.mark_error(report.schema_errors, f"{prefix}: text must be a non-empty string")
        return False
    if entity["type"] not in TARGET_ENTITY_TYPES:
        report.mark_error(report.schema_errors, f"{prefix}: invalid type {entity['type']!r}")
        return False
    if not isinstance(entity["position"], list) or len(entity["position"]) != 2:
        report.mark_error(report.schema_errors, f"{prefix}: position must be [start, end]")
        return False
    if not all(isinstance(value, int) for value in entity["position"]):
        report.mark_error(report.schema_errors, f"{prefix}: position values must be integers")
        return False
    if not isinstance(entity["assertions"], list):
        report.mark_error(report.schema_errors, f"{prefix}: assertions must be a list")
        return False
    if len(entity["assertions"]) != len(set(entity["assertions"])):
        report.mark_error(report.schema_errors, f"{prefix}: duplicate assertions")
        return False
    invalid_assertions = [assertion for assertion in entity["assertions"] if assertion not in ALLOWED_ASSERTIONS]
    if invalid_assertions:
        report.mark_error(report.schema_errors, f"{prefix}: invalid assertions {invalid_assertions}")
        return False
    if entity["type"] in LAB_TYPES and entity["assertions"]:
        report.mark_error(report.schema_errors, f"{prefix}: lab entity must not have assertions")
        return False

    if entity["type"] in MAPPING_TYPES:
        if "candidates" not in entity or not isinstance(entity["candidates"], list):
            report.mark_error(report.schema_errors, f"{prefix}: diagnosis/drug candidates must be a list")
            return False
        if not all(isinstance(candidate, str) for candidate in entity["candidates"]):
            report.mark_error(report.schema_errors, f"{prefix}: candidates must contain strings")
            return False
    elif "candidates" in entity:
        report.mark_error(report.schema_errors, f"{prefix}: candidates only allowed for diagnosis/drug")
        return False

    return True


def _validate_offsets(file_id: str, index: int, entity: Dict[str, object], doc: ClinicalDocument, report: ValidationReport) -> None:
    """Validate final raw offsets."""
    start, end = entity["position"]
    if not (0 <= start < end <= len(doc.raw_text)):
        report.mark_error(report.offset_errors, f"{file_id}.json[{index}]: invalid offset range {start}:{end}")
        return
    if doc.raw_text[start:end] != entity["text"]:
        report.mark_error(
            report.offset_errors,
            f"{file_id}.json[{index}]: offset text mismatch at {start}:{end}",
        )


def _validate_no_overlaps(file_id: str, entities: Sequence[Dict[str, object]], report: ValidationReport) -> None:
    """Ensure final output has no overlapping spans within a file."""
    spans = sorted(
        ((entity["position"][0], entity["position"][1], index) for index, entity in enumerate(entities)),
        key=lambda item: (item[0], item[1]),
    )
    previous = None
    for span in spans:
        if previous is not None and span[0] < previous[1]:
            report.mark_error(
                report.overlap_errors,
                f"{file_id}.json: entity {previous[2]} overlaps entity {span[2]}",
            )
        previous = span


def _validate_zip(zip_path: Path, expected_file_ids: Sequence[str], report: ValidationReport) -> None:
    """Validate output.zip top-level structure."""
    expected_names = {f"output/{file_id}.json" for file_id in expected_file_ids}
    if not zip_path.exists():
        report.mark_error(report.zip_errors, f"missing zip file {zip_path}")
        return

    with zipfile.ZipFile(zip_path, "r") as zipf:
        names = {name for name in zipf.namelist() if not name.endswith("/")}
    if names != expected_names:
        missing = sorted(expected_names - names)
        extra = sorted(names - expected_names)
        if missing:
            report.mark_error(report.zip_errors, f"zip missing files: {missing[:10]}")
        if extra:
            report.mark_error(report.zip_errors, f"zip has extra files: {extra[:10]}")


def validate_output_artifacts(
    output_dir: str | Path,
    zip_path: str | Path,
    documents_by_id: Dict[str, ClinicalDocument],
    expected_file_ids: Iterable[str],
) -> ValidationReport:
    """Validate V0 output JSON files and zip package."""
    output_path = Path(output_dir)
    archive_path = Path(zip_path)
    expected_ids = sorted((str(file_id) for file_id in expected_file_ids), key=_numeric_file_id)
    report = ValidationReport()
    seen_entities = set()

    for file_id in expected_ids:
        file_path = output_path / f"{file_id}.json"
        doc = documents_by_id.get(file_id)
        if doc is None:
            report.mark_error(report.schema_errors, f"{file_id}.json: missing source document")
            continue
        if not file_path.exists():
            report.mark_error(report.schema_errors, f"{file_id}.json: missing output file")
            continue

        try:
            entities = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.mark_error(report.schema_errors, f"{file_id}.json: invalid JSON {exc}")
            continue

        if not isinstance(entities, list):
            report.mark_error(report.schema_errors, f"{file_id}.json: root must be a list")
            continue
        if not entities:
            report.empty_files.append(file_id)

        valid_entities: List[Dict[str, object]] = []
        for index, entity in enumerate(entities):
            if not _validate_schema(file_id, index, entity, report):
                continue
            identity = _entity_identity(file_id, entity)
            if identity in seen_entities:
                report.mark_error(report.duplicate_errors, f"{file_id}.json[{index}]: duplicate exact entity")
            seen_entities.add(identity)
            _validate_offsets(file_id, index, entity, doc, report)
            report.total_entities += 1
            report.by_type[entity["type"]] += 1
            for assertion in entity["assertions"]:
                report.by_assertion[assertion] += 1
            valid_entities.append(entity)

        _validate_no_overlaps(file_id, valid_entities, report)

    _validate_zip(archive_path, expected_ids, report)
    return report


def write_validation_report(report: ValidationReport, path: str | Path) -> None:
    """Write a compact Markdown validation report."""
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Validation V0",
        "",
        f"Status: {'PASS' if report.ok else 'FAIL'}",
        f"Total entities: {report.total_entities}",
        f"By type: {dict(report.by_type)}",
        f"By assertion: {dict(report.by_assertion)}",
        f"Empty files: {report.empty_files}",
        "",
        "## Error Counts",
        "",
        f"- Schema errors: {len(report.schema_errors)}",
        f"- Offset errors: {len(report.offset_errors)}",
        f"- Duplicate errors: {len(report.duplicate_errors)}",
        f"- Overlap errors: {len(report.overlap_errors)}",
        f"- Zip errors: {len(report.zip_errors)}",
    ]

    errors = (
        report.schema_errors
        + report.offset_errors
        + report.duplicate_errors
        + report.overlap_errors
        + report.zip_errors
    )
    if errors:
        lines.extend(["", "## First Errors", ""])
        lines.extend(f"- {error}" for error in errors[:50])

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
