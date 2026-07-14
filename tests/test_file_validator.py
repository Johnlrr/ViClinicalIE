from __future__ import annotations

from src.config import load_config
from src.io_utils import read_json, write_json, write_text
from src.validation import validate_prediction_directory, validate_prediction_file, write_directory_validation_report


def test_validate_prediction_file_valid(tmp_path) -> None:
    raw_path = tmp_path / "input" / "1.txt"
    pred_path = tmp_path / "pred" / "1.json"
    write_text(raw_path, "sốt")
    write_json(pred_path, [{"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []}])

    report = validate_prediction_file(pred_path, raw_path)

    assert report.error_count == 0
    assert report.entity_count == 1


def test_validate_prediction_file_invalid_json_and_empty_file(tmp_path) -> None:
    raw_path = tmp_path / "input" / "1.txt"
    invalid_path = tmp_path / "pred" / "1.json"
    empty_path = tmp_path / "pred" / "2.json"
    write_text(raw_path, "sốt")
    write_text(invalid_path, "[")
    write_text(empty_path, "")

    invalid_report = validate_prediction_file(invalid_path, raw_path)
    empty_report = validate_prediction_file(empty_path, raw_path)

    assert invalid_report.issue_counts_by_code(level="error")["json_parse_error"] == 1
    assert empty_report.issue_counts_by_code(level="error")["prediction_file_empty"] == 1


def test_validate_prediction_directory_missing_and_extra_files(tmp_path) -> None:
    input_dir = tmp_path / "input"
    pred_dir = tmp_path / "pred"
    write_text(input_dir / "1.txt", "sốt")
    write_text(input_dir / "2.txt", "ho")
    write_json(pred_dir / "1.json", [{"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []}])
    write_json(pred_dir / "3.json", [])

    report = validate_prediction_directory(input_dir, pred_dir, expected_count=2)

    counts = report.issue_counts_by_code(level="error")
    assert counts["prediction_file_missing"] == 1
    assert counts["extra_prediction_file"] == 1
    assert report.entities_checked == 1


def test_write_directory_validation_report(tmp_path) -> None:
    input_dir = tmp_path / "input"
    pred_dir = tmp_path / "pred"
    report_dir = tmp_path / "report"
    write_text(input_dir / "1.txt", "sốt")
    write_json(pred_dir / "1.json", [{"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []}])

    report = validate_prediction_directory(input_dir, pred_dir)
    write_directory_validation_report(report, report_dir)

    summary = read_json(report_dir / "validation_summary.json")
    assert summary["error_count"] == 0
    assert (report_dir / "validation_issues.jsonl").is_file()


def test_golden_directory_validation_passes_without_errors(tmp_path) -> None:
    config = load_config("configs/default.yaml")
    report = validate_prediction_directory(
        config.path("golden_input_dir"),
        config.path("golden_gold_dir"),
        expected_count=20,
        config=config.raw.get("prediction_validation", {}),
    )
    assert report.error_count == 0
    assert report.files_checked == 20
    assert report.entities_checked == 370