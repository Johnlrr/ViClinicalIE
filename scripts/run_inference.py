from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import load_config
from src.formatting.json_formatter import write_prediction_json
from src.pipeline import ClinicalIEPipeline
from src.validation.file_validator import DirectoryValidationReport, validate_prediction_file, write_directory_validation_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end clinical IE inference and write prediction JSON files.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--input-dir", default=None, help="Directory containing input .txt files. Defaults to raw_input_dir in config.")
    parser.add_argument("--output-dir", default="outputs/predictions/submission_trial/output", help="Directory to write prediction .json files.")
    parser.add_argument("--report-dir", default="outputs/reports/submission_trial_validation", help="Directory to write validation report.")
    parser.add_argument("--expected-count", type=int, default=None, help="Expected number of processed input files.")
    parser.add_argument("--max-files", type=int, default=None, help="Optional maximum files to process for smoke runs.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset into sorted input files.")
    parser.add_argument("--keep-existing-output", action="store_true", help="Do not delete existing *.json files in output dir before writing.")
    parser.add_argument("--disable-sparse-retrieval", action="store_true", help="Disable TF-IDF/BM25 linker retrieval for faster smoke runs.")
    parser.add_argument("--skip-validation", action="store_true", help="Skip post-write schema/offset validation.")
    parser.add_argument("--sample-limit", type=int, default=20, help="Maximum validation issues to print.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    input_dir = _resolve_project_path(args.input_dir) if args.input_dir else config.path("raw_input_dir")
    output_dir = _resolve_project_path(args.output_dir)
    report_dir = _resolve_project_path(args.report_dir)
    files = _select_files(input_dir, max_files=args.max_files, start_index=args.start_index)
    if args.expected_count is not None and len(files) != args.expected_count:
        raise ValueError(f"Selected file count mismatch: expected {args.expected_count}, got {len(files)}")
    if not files:
        raise FileNotFoundError(f"No .txt files found in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    if not args.keep_existing_output:
        for stale in output_dir.glob("*.json"):
            stale.unlink(missing_ok=True)

    pipeline = ClinicalIEPipeline(config, enable_sparse_retrieval=not args.disable_sparse_retrieval)
    output_format_cfg = config.raw.get("output_format", {})
    total_counters: Counter[str] = Counter()
    entity_counts: Counter[str] = Counter()
    for index, path in enumerate(files, start=1):
        result = pipeline.process_file(path)
        output_path = output_dir / f"{path.stem}.json"
        write_prediction_json(result.records, output_path, output_format_cfg)
        total_counters.update(result.counters)
        entity_counts.update(result.entities_by_type)
        print(f"[{index}/{len(files)}] wrote {output_path.name}: records={len(result.records)}")

    validation_report: DirectoryValidationReport | None = None
    if not args.skip_validation:
        validation_report = _validate_selected_files(files, output_dir, config.raw.get("prediction_validation", {}))
        write_directory_validation_report(validation_report, report_dir)

    print("Inference completed.")
    print(f"input_dir: {input_dir}")
    print(f"output_dir: {output_dir}")
    print(f"files_processed: {len(files)}")
    print(f"records_written: {total_counters.get('records', 0)}")
    print(f"chunks: {total_counters.get('chunks', 0)}")
    print(f"span_candidates: {total_counters.get('span_candidates', 0)}")
    print(f"entities_before_postprocess: {total_counters.get('entities_before_postprocess', 0)}")
    print(f"entities_after_postprocess: {total_counters.get('entities_after_postprocess', 0)}")
    print(f"postprocess_entities_dropped: {total_counters.get('postprocess_entities_dropped', 0)}")
    print(f"postprocess_overlap_resolutions: {total_counters.get('postprocess_overlap_resolutions', 0)}")
    print(f"entities_by_type: {dict(sorted(entity_counts.items()))}")
    if validation_report is not None:
        error_counts = validation_report.issue_counts_by_code(level="error")
        print(f"validation_error_count: {validation_report.error_count}")
        print(f"validation_warning_count: {validation_report.warning_count}")
        print(f"missing_prediction_count: {len(validation_report.missing_files)}")
        print(f"extra_prediction_count: {len(validation_report.extra_files)}")
        print(f"offset_error_count: {error_counts.get('offset_mismatch', 0) + error_counts.get('position_out_of_bounds', 0)}")
        print(f"schema_error_count: {sum(count for code, count in error_counts.items() if code not in {'offset_mismatch', 'position_out_of_bounds'})}")
        print(f"invalid_type_count: {error_counts.get('invalid_type', 0)}")
        print(f"invalid_assertion_count: {error_counts.get('invalid_assertion', 0)}")
        print(f"wrong_type_candidate_count: {error_counts.get('non_linked_type_has_candidates', 0)}")
        print(f"report_dir: {report_dir}")
        for issue in validation_report.issues[: args.sample_limit]:
            print(
                f"{issue.level.upper()} {issue.code} file={issue.file_name} "
                f"index={issue.entity_index} field={issue.field} message={issue.message} value={issue.value}"
            )
        return 1 if validation_report.error_count else 0
    return 0


def _select_files(input_dir: Path, *, max_files: int | None, start_index: int) -> list[Path]:
    files = sorted(input_dir.glob("*.txt"), key=lambda item: _natural_stem_key(item.stem))
    if start_index:
        files = files[start_index:]
    if max_files is not None:
        files = files[:max_files]
    return files


def _validate_selected_files(files: list[Path], output_dir: Path, validation_cfg: dict) -> DirectoryValidationReport:
    report = DirectoryValidationReport(input_dir=";".join(sorted({str(path.parent) for path in files})), pred_dir=str(output_dir))
    report.files_checked = len(files)
    for input_file in files:
        prediction_file = output_dir / f"{input_file.stem}.json"
        if not prediction_file.is_file():
            report.missing_files.append(prediction_file.name)
            continue
        file_report = validate_prediction_file(prediction_file, input_file, validation_cfg)
        report.file_reports.append(file_report)
        report.prediction_files_checked += 1
        report.entities_checked += file_report.entity_count
        report.issues.extend(file_report.issues)
    selected_stems = {path.stem for path in files}
    for prediction_file in sorted(output_dir.glob("*.json"), key=lambda item: _natural_stem_key(item.stem)):
        if prediction_file.stem not in selected_stems:
            report.extra_files.append(prediction_file.name)
    return report


def _natural_stem_key(stem: str) -> tuple[int, int | str]:
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())