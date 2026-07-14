from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.io_utils import append_jsonl, read_json, read_text, write_json, write_text
from src.validation.prediction_schema import ValidationIssue, ValidationReport, validate_prediction_records


@dataclass(slots=True)
class DirectoryValidationReport:
    input_dir: str
    pred_dir: str
    files_checked: int = 0
    prediction_files_checked: int = 0
    entities_checked: int = 0
    missing_files: list[str] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    file_reports: list[ValidationReport] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "warning")

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def issue_counts_by_code(self, *, level: str | None = None) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for issue in self.issues:
            if level is not None and issue.level != level:
                continue
            counter[issue.code] += 1
        return dict(sorted(counter.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_dir": self.input_dir,
            "pred_dir": self.pred_dir,
            "files_checked": self.files_checked,
            "prediction_files_checked": self.prediction_files_checked,
            "entities_checked": self.entities_checked,
            "missing_prediction_count": len(self.missing_files),
            "extra_prediction_count": len(self.extra_files),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "ok": self.ok,
            "issue_counts_by_code": self.issue_counts_by_code(),
            "missing_files": list(self.missing_files),
            "extra_files": list(self.extra_files),
            "files": [report.to_dict() for report in self.file_reports],
        }


def validate_prediction_file(
    prediction_path: str | Path,
    raw_text_path: str | Path,
    config: Mapping[str, Any] | None = None,
) -> ValidationReport:
    pred_path = Path(prediction_path)
    raw_path = Path(raw_text_path)
    report = ValidationReport(file_name=pred_path.name)
    try:
        raw_text = read_text(raw_path)
    except OSError as exc:
        report.issues.append(
            ValidationIssue("error", "raw_file_read_error", f"Could not read raw text file: {exc}", file_name=pred_path.name, value=str(raw_path))
        )
        return report
    try:
        raw_prediction_text = read_text(pred_path)
    except OSError as exc:
        report.issues.append(
            ValidationIssue("error", "prediction_file_read_error", f"Could not read prediction JSON file: {exc}", file_name=pred_path.name, value=str(pred_path))
        )
        return report
    if raw_prediction_text.strip() == "":
        report.issues.append(ValidationIssue("error", "prediction_file_empty", "Prediction JSON file is empty", file_name=pred_path.name, value=str(pred_path)))
        return report
    try:
        records = json.loads(raw_prediction_text)
    except json.JSONDecodeError as exc:
        report.issues.append(ValidationIssue("error", "json_parse_error", f"Prediction JSON parse error: {exc}", file_name=pred_path.name, value=str(pred_path)))
        return report
    return validate_prediction_records(records, raw_text, file_name=pred_path.name, config=config)


def validate_prediction_directory(
    input_dir: str | Path,
    pred_dir: str | Path,
    *,
    expected_count: int | None = None,
    config: Mapping[str, Any] | None = None,
) -> DirectoryValidationReport:
    input_path = Path(input_dir)
    pred_path = Path(pred_dir)
    report = DirectoryValidationReport(input_dir=str(input_path), pred_dir=str(pred_path))
    input_files = sorted(input_path.glob("*.txt"), key=lambda item: _natural_stem_key(item.stem))
    prediction_files = sorted(pred_path.glob("*.json"), key=lambda item: _natural_stem_key(item.stem)) if pred_path.is_dir() else []
    report.files_checked = len(input_files)
    if expected_count is not None and len(input_files) != expected_count:
        report.issues.append(
            ValidationIssue("error", "input_count_mismatch", "Input file count does not match expected count", value={"expected": expected_count, "actual": len(input_files)})
        )

    prediction_by_stem = {path.stem: path for path in prediction_files}
    input_stems = {path.stem for path in input_files}
    for input_file in input_files:
        prediction_file = prediction_by_stem.get(input_file.stem)
        if prediction_file is None:
            missing_name = f"{input_file.stem}.json"
            report.missing_files.append(missing_name)
            report.issues.append(ValidationIssue("error", "prediction_file_missing", "Missing prediction JSON for input file", file_name=missing_name, value=str(input_file)))
            continue
        file_report = validate_prediction_file(prediction_file, input_file, config=config)
        report.file_reports.append(file_report)
        report.prediction_files_checked += 1
        report.entities_checked += file_report.entity_count
        report.issues.extend(file_report.issues)

    for prediction_file in prediction_files:
        if prediction_file.stem not in input_stems:
            report.extra_files.append(prediction_file.name)
            report.issues.append(ValidationIssue("error", "extra_prediction_file", "Prediction JSON has no matching input text file", file_name=prediction_file.name, value=str(prediction_file)))
    return report


def write_directory_validation_report(report: DirectoryValidationReport, report_dir: str | Path) -> None:
    target = Path(report_dir)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "validation_summary.json", report.to_dict())
    issues_path = target / "validation_issues.jsonl"
    write_text(issues_path, "")
    for issue in report.issues:
        append_jsonl(issues_path, issue.to_dict())


def _natural_stem_key(stem: str) -> tuple[int, int | str]:
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)