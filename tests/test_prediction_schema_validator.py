from __future__ import annotations

import math

from src.config import load_config
from src.io_utils import read_json, read_text
from src.validation import validate_prediction_records


def test_valid_records_for_all_entity_types() -> None:
    raw_text = "sốt Na 140 viêm phổi aspirin"
    records = [
        {"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": ["isNegated"]},
        {"text": "Na", "position": [4, 6], "type": "TÊN_XÉT_NGHIỆM", "assertions": []},
        {"text": "140", "position": [7, 10], "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": []},
        {"text": "viêm phổi", "position": [11, 20], "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["J18.9"]},
        {"text": "aspirin", "position": [21, 28], "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
    ]

    report = validate_prediction_records(records, raw_text)

    assert report.error_count == 0


def test_top_level_must_be_list() -> None:
    report = validate_prediction_records({"text": "sốt"}, "sốt")
    assert report.issue_counts_by_code(level="error")["top_level_not_list"] == 1


def test_record_must_be_object() -> None:
    report = validate_prediction_records(["bad"], "bad")
    assert report.issue_counts_by_code(level="error")["record_not_object"] == 1


def test_missing_and_extra_fields_are_errors() -> None:
    report = validate_prediction_records([{"text": "sốt", "position": [0, 3], "confidence": 0.9}], "sốt")
    counts = report.issue_counts_by_code(level="error")
    assert counts["missing_field"] >= 2
    assert counts["extra_field"] == 1


def test_invalid_type_and_assertion_are_errors() -> None:
    record = {"text": "sốt", "position": [0, 3], "type": "BAD", "assertions": ["badAssertion"]}
    report = validate_prediction_records([record], "sốt")
    counts = report.issue_counts_by_code(level="error")
    assert counts["invalid_type"] == 1
    assert counts["invalid_assertion"] == 1


def test_non_linked_candidates_and_linked_missing_candidates_are_errors() -> None:
    raw_text = "sốt viêm phổi"
    records = [
        {"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
        {"text": "viêm phổi", "position": [4, 13], "type": "CHẨN_ĐOÁN", "assertions": []},
    ]
    report = validate_prediction_records(records, raw_text)
    counts = report.issue_counts_by_code(level="error")
    assert counts["non_linked_type_has_candidates"] == 1
    assert counts["candidates_missing"] == 1


def test_candidate_validation_errors_and_warnings() -> None:
    record = {"text": "aspirin", "position": [0, 7], "type": "THUỐC", "assertions": [], "candidates": ["1191", "", 123, "1191"]}
    report = validate_prediction_records([record], "aspirin")
    error_counts = report.issue_counts_by_code(level="error")
    warning_counts = report.issue_counts_by_code(level="warning")
    assert error_counts["candidate_empty"] == 1
    assert error_counts["candidate_not_string"] == 1
    assert warning_counts["duplicate_candidate"] == 1


def test_position_validation_and_offset_mismatch() -> None:
    records = [
        {"text": "sốt", "position": [True, 3], "type": "TRIỆU_CHỨNG", "assertions": []},
        {"text": "sốt", "position": [0, 99], "type": "TRIỆU_CHỨNG", "assertions": []},
        {"text": "ho", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []},
    ]
    report = validate_prediction_records(records, "sốt")
    counts = report.issue_counts_by_code(level="error")
    assert counts["position_not_int"] == 1
    assert counts["position_out_of_bounds"] == 1
    assert counts["offset_mismatch"] == 1


def test_empty_text_none_nan_inf_are_errors() -> None:
    records = [
        {"text": "", "position": [0, 1], "type": "TRIỆU_CHỨNG", "assertions": []},
        {"text": None, "position": [0, 1], "type": "TRIỆU_CHỨNG", "assertions": []},
        {"text": "a", "position": [0, 1], "type": "TRIỆU_CHỨNG", "assertions": [], "score": math.nan},
        {"text": "a", "position": [0, 1], "type": "TRIỆU_CHỨNG", "assertions": [], "score": math.inf},
    ]
    report = validate_prediction_records(records, "a")
    counts = report.issue_counts_by_code(level="error")
    assert counts["text_empty"] == 1
    assert counts["none_value"] >= 1
    assert counts["nan_value"] == 1
    assert counts["infinite_value"] == 1


def test_duplicate_exact_is_warning_not_error() -> None:
    record = {"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []}
    report = validate_prediction_records([record, dict(record)], "sốt")
    assert report.error_count == 0
    assert report.issue_counts_by_code(level="warning")["duplicate_exact_span_type"] == 1


def test_golden_gold_files_pass_schema_validation() -> None:
    config = load_config("configs/default.yaml")
    validation_cfg = config.raw.get("prediction_validation", {})
    for item_id in range(1, 21):
        raw_text = read_text(config.path("golden_input_dir") / f"{item_id}.txt")
        records = read_json(config.path("golden_gold_dir") / f"{item_id}.json")
        report = validate_prediction_records(records, raw_text, file_name=f"{item_id}.json", config=validation_cfg)
        assert report.error_count == 0, (item_id, report.issue_counts_by_code(level="error"))