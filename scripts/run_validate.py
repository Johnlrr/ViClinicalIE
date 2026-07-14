from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import load_config
from src.validation import validate_prediction_directory, write_directory_validation_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate prediction JSON files against raw text inputs.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--input-dir", required=True, help="Directory containing raw .txt files.")
    parser.add_argument("--pred-dir", required=True, help="Directory containing prediction .json files.")
    parser.add_argument("--report-dir", default=None, help="Directory to write validation reports.")
    parser.add_argument("--expected-count", type=int, default=None, help="Expected number of input .txt files.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return non-zero when warnings are present.")
    parser.add_argument("--sample-limit", type=int, default=20, help="Maximum sample issues to print.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    validation_cfg = config.raw.get("prediction_validation", {})
    report = validate_prediction_directory(args.input_dir, args.pred_dir, expected_count=args.expected_count, config=validation_cfg)
    if args.report_dir:
        write_directory_validation_report(report, args.report_dir)

    error_counts = report.issue_counts_by_code(level="error")
    warning_counts = report.issue_counts_by_code(level="warning")
    print("Prediction validation completed.")
    print(f"input_files_checked: {report.files_checked}")
    print(f"prediction_files_checked: {report.prediction_files_checked}")
    print(f"entities_checked: {report.entities_checked}")
    print(f"missing_prediction_count: {len(report.missing_files)}")
    print(f"extra_prediction_count: {len(report.extra_files)}")
    print(f"error_count: {report.error_count}")
    print(f"warning_count: {report.warning_count}")
    print(f"offset_error_count: {error_counts.get('offset_mismatch', 0) + error_counts.get('position_out_of_bounds', 0)}")
    print(f"schema_error_count: {sum(count for code, count in error_counts.items() if code not in {'offset_mismatch', 'position_out_of_bounds'})}")
    print(f"invalid_type_count: {error_counts.get('invalid_type', 0)}")
    print(f"invalid_assertion_count: {error_counts.get('invalid_assertion', 0)}")
    print(f"wrong_type_candidate_count: {error_counts.get('non_linked_type_has_candidates', 0)}")
    print(f"json_parse_error_count: {error_counts.get('json_parse_error', 0)}")
    if args.report_dir:
        print(f"report_dir: {args.report_dir}")
    for issue in report.issues[: args.sample_limit]:
        print(
            f"{issue.level.upper()} {issue.code} file={issue.file_name} "
            f"index={issue.entity_index} field={issue.field} message={issue.message} value={issue.value}"
        )
    if report.error_count or (args.fail_on_warning and report.warning_count):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())