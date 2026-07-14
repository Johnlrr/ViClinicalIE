from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from src.data_types import VALID_ASSERTIONS, VALID_ENTITY_TYPES
from src.postprocess.policies import ASSERTABLE_TYPES, LINKED_TYPES


@dataclass(slots=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    file_name: str | None = None
    entity_index: int | None = None
    field: str | None = None
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "file_name": self.file_name,
            "entity_index": self.entity_index,
            "field": self.field,
            "value": self.value,
        }


@dataclass(slots=True)
class ValidationReport:
    file_name: str | None = None
    entity_count: int = 0
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
            "file_name": self.file_name,
            "entity_count": self.entity_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "ok": self.ok,
            "issue_counts_by_code": self.issue_counts_by_code(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_prediction_records(
    records: Any,
    raw_text: str,
    *,
    file_name: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> ValidationReport:
    cfg = dict(config or {})
    report = ValidationReport(file_name=file_name)
    _add_invalid_json_value_issues(records, report, path="$")
    if not isinstance(records, list):
        _add_issue(report, "error", "top_level_not_list", "Prediction JSON top-level value must be a list", file_name=file_name)
        return report

    report.entity_count = len(records)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            _add_issue(report, "error", "record_not_object", "Each prediction item must be an object", file_name=file_name, entity_index=index, value=record)
            continue
        _validate_record(record, raw_text, report, index, file_name, cfg)

    if bool(cfg.get("warn_on_duplicate_exact", True)):
        _add_duplicate_exact_warnings(records, report, file_name)
    if bool(cfg.get("warn_on_overlap", False)):
        _add_overlap_warnings(records, report, file_name)
    return report


def _validate_record(
    record: dict[str, Any],
    raw_text: str,
    report: ValidationReport,
    index: int,
    file_name: str | None,
    config: dict[str, Any],
) -> None:
    allow_extra = bool(config.get("allow_extra_fields", False))
    require_assertions = bool(config.get("require_assertions_field", True))
    require_linked_candidates = bool(config.get("require_candidates_for_linked_types", True))
    forbid_non_linked_candidates = bool(config.get("forbid_candidates_for_non_linked_types", True))

    entity_type = record.get("type")
    entity_type_text = entity_type if isinstance(entity_type, str) else None
    linked_type = entity_type_text in LINKED_TYPES

    required_fields = {"text", "position", "type"}
    if require_assertions:
        required_fields.add("assertions")
    if linked_type and require_linked_candidates:
        required_fields.add("candidates")
    for field_name in sorted(required_fields):
        if field_name not in record:
            _add_issue(report, "error", "missing_field", f"Missing required field: {field_name}", file_name=file_name, entity_index=index, field=field_name)

    allowed_fields = {"text", "position", "type", "assertions"}
    if linked_type:
        allowed_fields.add("candidates")
    if not allow_extra:
        for field_name in sorted(set(record) - allowed_fields):
            _add_issue(report, "error", "extra_field", f"Unexpected field: {field_name}", file_name=file_name, entity_index=index, field=field_name, value=record.get(field_name))

    text = record.get("text")
    if not isinstance(text, str):
        _add_issue(report, "error", "text_not_string", "Field text must be a string", file_name=file_name, entity_index=index, field="text", value=text)
    elif text == "":
        _add_issue(report, "error", "text_empty", "Field text must not be empty", file_name=file_name, entity_index=index, field="text", value=text)

    if not isinstance(entity_type, str):
        _add_issue(report, "error", "type_not_string", "Field type must be a string", file_name=file_name, entity_index=index, field="type", value=entity_type)
    elif entity_type not in VALID_ENTITY_TYPES:
        _add_issue(report, "error", "invalid_type", "Invalid entity type", file_name=file_name, entity_index=index, field="type", value=entity_type)

    start_end = _validate_position(record.get("position"), raw_text, text, report, index, file_name)
    _validate_assertions(record.get("assertions"), entity_type_text, report, index, file_name, require_assertions)
    _validate_candidates(record, entity_type_text, report, index, file_name, require_linked_candidates, forbid_non_linked_candidates)
    if start_end is not None and isinstance(text, str) and raw_text[start_end[0] : start_end[1]] != text:
        _add_issue(
            report,
            "error",
            "offset_mismatch",
            "raw_text[start:end] does not match text",
            file_name=file_name,
            entity_index=index,
            field="position",
            value={"position": [start_end[0], start_end[1]], "text": text, "raw_slice": raw_text[start_end[0] : start_end[1]]},
        )


def _validate_position(
    position: Any,
    raw_text: str,
    text: Any,
    report: ValidationReport,
    index: int,
    file_name: str | None,
) -> tuple[int, int] | None:
    if not isinstance(position, list) or len(position) != 2:
        _add_issue(report, "error", "position_not_pair", "Field position must be a list of two integers", file_name=file_name, entity_index=index, field="position", value=position)
        return None
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in position):
        _add_issue(report, "error", "position_not_int", "Position values must be non-bool integers", file_name=file_name, entity_index=index, field="position", value=position)
        return None
    start, end = int(position[0]), int(position[1])
    if not (0 <= start < end <= len(raw_text)):
        _add_issue(report, "error", "position_out_of_bounds", "Position must satisfy 0 <= start < end <= len(raw_text)", file_name=file_name, entity_index=index, field="position", value=position)
        return None
    return start, end


def _validate_assertions(
    assertions: Any,
    entity_type: str | None,
    report: ValidationReport,
    index: int,
    file_name: str | None,
    required: bool,
) -> None:
    if assertions is None:
        if required:
            _add_issue(report, "error", "assertions_missing", "Field assertions is required", file_name=file_name, entity_index=index, field="assertions")
        return
    if not isinstance(assertions, list):
        _add_issue(report, "error", "assertions_not_list", "Field assertions must be a list", file_name=file_name, entity_index=index, field="assertions", value=assertions)
        return
    seen: set[str] = set()
    for assertion in assertions:
        if not isinstance(assertion, str):
            _add_issue(report, "error", "assertion_not_string", "Assertions must be strings", file_name=file_name, entity_index=index, field="assertions", value=assertion)
            continue
        if assertion not in VALID_ASSERTIONS:
            _add_issue(report, "error", "invalid_assertion", "Invalid assertion value", file_name=file_name, entity_index=index, field="assertions", value=assertion)
        if assertion in seen:
            _add_issue(report, "error", "duplicate_assertion", "Duplicate assertion value", file_name=file_name, entity_index=index, field="assertions", value=assertion)
        seen.add(assertion)
    if entity_type not in ASSERTABLE_TYPES and assertions:
        _add_issue(report, "error", "non_assertable_type_has_assertion", "Non-assertable entity type must have empty assertions", file_name=file_name, entity_index=index, field="assertions", value=assertions)


def _validate_candidates(
    record: dict[str, Any],
    entity_type: str | None,
    report: ValidationReport,
    index: int,
    file_name: str | None,
    require_linked_candidates: bool,
    forbid_non_linked_candidates: bool,
) -> None:
    has_candidates = "candidates" in record
    candidates = record.get("candidates")
    if entity_type in LINKED_TYPES:
        if not has_candidates:
            if require_linked_candidates:
                _add_issue(report, "error", "candidates_missing", "Linked entity type must include candidates", file_name=file_name, entity_index=index, field="candidates")
            return
    elif has_candidates and forbid_non_linked_candidates:
        _add_issue(report, "error", "non_linked_type_has_candidates", "Non-linked entity type must not include candidates", file_name=file_name, entity_index=index, field="candidates", value=candidates)
    if not has_candidates:
        return
    if not isinstance(candidates, list):
        _add_issue(report, "error", "candidates_not_list", "Field candidates must be a list", file_name=file_name, entity_index=index, field="candidates", value=candidates)
        return
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            _add_issue(report, "error", "candidate_not_string", "Candidates must be strings", file_name=file_name, entity_index=index, field="candidates", value=candidate)
            continue
        if candidate == "":
            _add_issue(report, "error", "candidate_empty", "Candidate strings must not be empty", file_name=file_name, entity_index=index, field="candidates", value=candidate)
        if candidate in seen:
            _add_issue(report, "warning", "duplicate_candidate", "Duplicate candidate value", file_name=file_name, entity_index=index, field="candidates", value=candidate)
        seen.add(candidate)


def _add_invalid_json_value_issues(value: Any, report: ValidationReport, path: str) -> None:
    if value is None:
        _add_issue(report, "error", "none_value", "JSON value must not be null", file_name=report.file_name, field=path)
        return
    if isinstance(value, float):
        if math.isnan(value):
            _add_issue(report, "error", "nan_value", "JSON value must not be NaN", file_name=report.file_name, field=path)
        elif math.isinf(value):
            _add_issue(report, "error", "infinite_value", "JSON value must not be infinite", file_name=report.file_name, field=path)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _add_invalid_json_value_issues(child, report, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _add_invalid_json_value_issues(child, report, f"{path}[{index}]")


def _add_duplicate_exact_warnings(records: list[Any], report: ValidationReport, file_name: str | None) -> None:
    seen: dict[tuple[int, int, str], int] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        position = record.get("position")
        entity_type = record.get("type")
        if not (isinstance(position, list) and len(position) == 2 and all(isinstance(item, int) and not isinstance(item, bool) for item in position) and isinstance(entity_type, str)):
            continue
        key = (position[0], position[1], entity_type)
        first_index = seen.get(key)
        if first_index is None:
            seen[key] = index
        else:
            _add_issue(report, "warning", "duplicate_exact_span_type", "Duplicate exact (start, end, type) prediction", file_name=file_name, entity_index=index, field="position", value={"first_index": first_index, "position": position, "type": entity_type})


def _add_overlap_warnings(records: list[Any], report: ValidationReport, file_name: str | None) -> None:
    intervals: list[tuple[int, int, str, int]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        position = record.get("position")
        entity_type = record.get("type")
        if isinstance(position, list) and len(position) == 2 and all(isinstance(item, int) and not isinstance(item, bool) for item in position) and isinstance(entity_type, str):
            intervals.append((position[0], position[1], entity_type, index))
    intervals.sort()
    for i, first in enumerate(intervals):
        for second in intervals[i + 1 :]:
            if second[0] >= first[1]:
                break
            if _interval_overlap_len(first, second) > 0:
                _add_issue(report, "warning", "overlapping_entities", "Prediction entities overlap", file_name=file_name, entity_index=second[3], field="position", value={"first_index": first[3], "second_index": second[3], "first": [first[0], first[1], first[2]], "second": [second[0], second[1], second[2]]})


def _interval_overlap_len(first: tuple[int, int, str, int], second: tuple[int, int, str, int]) -> int:
    return max(0, min(first[1], second[1]) - max(first[0], second[0]))


def _add_issue(
    report: ValidationReport,
    level: str,
    code: str,
    message: str,
    *,
    file_name: str | None = None,
    entity_index: int | None = None,
    field: str | None = None,
    value: Any = None,
) -> None:
    report.issues.append(
        ValidationIssue(
            level=level,
            code=code,
            message=message,
            file_name=file_name,
            entity_index=entity_index,
            field=field,
            value=value,
        )
    )