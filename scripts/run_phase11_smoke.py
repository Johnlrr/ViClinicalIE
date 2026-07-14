from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.assertion import AssertionDetector, load_assertion_rules
from src.config import load_config
from src.extractors import ExtractionContext, build_default_extractors
from src.formatting import PredictionFormatter
from src.io_utils import read_text
from src.linking.icd10_linker import ICD10Linker
from src.linking.rxnorm_linker import RxNormLinker
from src.postprocess import Postprocessor
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import detect_sections, load_section_patterns
from src.type_resolution import TypeResolver
from src.validation.file_validator import DirectoryValidationReport, validate_prediction_file, write_directory_validation_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 11 formatter/validator smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=2, help="Maximum files to check.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset into the sampled file list for batched smoke runs.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Maximum sample issues to print.")
    parser.add_argument("--prediction-dir", default="outputs/predictions/phase11_smoke", help="Directory to write smoke prediction JSON files.")
    parser.add_argument("--report-dir", default="outputs/reports/phase11_smoke_validation", help="Directory to write validation reports.")
    parser.add_argument("--keep-existing-output", action="store_true", help="Do not remove existing prediction JSON files before writing the current batch.")
    parser.add_argument(
        "--enable-sparse-retrieval",
        action="store_true",
        help="Use configured TF-IDF/BM25 linker retrieval. By default Phase 11 smoke uses exact-linking only for speed.",
    )
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    raw_config = copy.deepcopy(config.raw)
    if not args.enable_sparse_retrieval:
        _disable_sparse_linker_retrieval(raw_config)

    section_cfg = raw_config.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    extractors = build_default_extractors(config)
    resolver = TypeResolver(raw_config.get("type_resolution", {}))
    assertion_cfg = dict(raw_config.get("assertion_detection", {}))
    rules = _load_assertion_rules(config.config_path, assertion_cfg)
    detector = AssertionDetector(assertion_cfg, rules=rules)
    icd_linker = ICD10Linker(config.path("processed_dir"), raw_config.get("icd10_linking", {}))
    rx_linker = RxNormLinker(config.path("processed_dir"), raw_config.get("rxnorm_linking", {}))
    postprocessor = Postprocessor(raw_config.get("postprocess", {}))
    formatter = PredictionFormatter(raw_config.get("output_format", {}))
    validation_cfg = raw_config.get("prediction_validation", {})

    files = _sample_files(config, args.max_files, args.start_index)
    if not files:
        raise FileNotFoundError("No input files found for Phase 11 smoke check")
    prediction_dir = _resolve_project_path(args.prediction_dir)
    report_dir = _resolve_project_path(args.report_dir)
    prediction_dir.mkdir(parents=True, exist_ok=True)
    if not args.keep_existing_output:
        for stale in prediction_dir.glob("*.json"):
            stale.unlink(missing_ok=True)

    entity_counts: Counter[str] = Counter()
    report = DirectoryValidationReport(input_dir=";".join(str(path.parent) for path in files), pred_dir=str(prediction_dir))
    report.files_checked = len(files)
    total_chunks = 0
    total_span_candidates = 0
    total_before_format = 0
    total_records_written = 0
    total_postprocess_drops = 0
    total_postprocess_overlap_resolutions = 0

    for path in files:
        raw_text = read_text(path, encoding=str(raw_config.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, raw_config)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        total_chunks += len(chunks)
        context = ExtractionContext(raw_text=raw_text, views=output.views, chunks=chunks, config=raw_config)
        span_candidates = []
        for extractor in extractors:
            span_candidates.extend(extractor.extract(context))
        entities = resolver.resolve(span_candidates, raw_text)
        asserted = detector.apply(entities, raw_text)
        icd_linked = icd_linker.link_entities(asserted, raw_text=raw_text)
        linked = rx_linker.link_entities(icd_linked, raw_text=raw_text)
        postprocess_result = postprocessor.process(linked, raw_text=raw_text)
        postprocessed = postprocess_result.entities
        output_path = prediction_dir / f"{path.stem}.json"
        records = formatter.write(postprocessed, output_path)
        file_report = validate_prediction_file(output_path, path, config=validation_cfg)

        total_span_candidates += len(span_candidates)
        total_before_format += len(postprocessed)
        total_records_written += len(records)
        total_postprocess_drops += postprocess_result.report.entities_dropped
        total_postprocess_overlap_resolutions += postprocess_result.report.same_type_overlaps_resolved + postprocess_result.report.different_type_overlaps_resolved
        entity_counts.update(str(entity.type) for entity in postprocessed)
        report.file_reports.append(file_report)
        report.prediction_files_checked += 1
        report.entities_checked += file_report.entity_count
        report.issues.extend(file_report.issues)

    write_directory_validation_report(report, report_dir)
    error_counts = report.issue_counts_by_code(level="error")
    print("Phase 11 smoke checks completed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_checked: {total_chunks}")
    print(f"span_candidates: {total_span_candidates}")
    print(f"entities_before_format: {total_before_format}")
    print(f"records_written: {total_records_written}")
    print(f"postprocess_entities_dropped: {total_postprocess_drops}")
    print(f"postprocess_overlap_resolutions: {total_postprocess_overlap_resolutions}")
    print(f"entities_by_type: {dict(sorted(entity_counts.items()))}")
    print(f"validation_error_count: {report.error_count}")
    print(f"validation_warning_count: {report.warning_count}")
    print(f"offset_error_count: {error_counts.get('offset_mismatch', 0) + error_counts.get('position_out_of_bounds', 0)}")
    print(f"wrong_type_candidate_error_count: {error_counts.get('non_linked_type_has_candidates', 0)}")
    print(f"invalid_assertion_count: {error_counts.get('invalid_assertion', 0)}")
    print(f"prediction_dir: {prediction_dir}")
    print(f"report_dir: {report_dir}")
    for issue in report.issues[: args.sample_limit]:
        print(
            f"{issue.level.upper()} {issue.code} file={issue.file_name} "
            f"index={issue.entity_index} field={issue.field} message={issue.message} value={issue.value}"
        )
    return 1 if report.error_count else 0


def _resolve_patterns_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _load_assertion_rules(config_path: Path, assertion_cfg: dict[str, Any]) -> dict[str, list[str]]:
    rules_value = assertion_cfg.get("rules_config")
    if not rules_value:
        return {}
    rules_path = _resolve_patterns_path(config_path, str(rules_value))
    return load_assertion_rules(rules_path)


def _disable_sparse_linker_retrieval(raw_config: dict[str, Any]) -> None:
    for section_name in ("icd10_linking", "rxnorm_linking"):
        section = raw_config.get(section_name, {})
        if not isinstance(section, dict):
            continue
        retrieval = section.setdefault("retrieval", {})
        if not isinstance(retrieval, dict):
            retrieval = {}
            section["retrieval"] = retrieval
        retrieval["top_k_tfidf"] = 0
        retrieval["top_k_bm25"] = 0


def _sample_files(config, max_files: int, start_index: int = 0) -> list[Path]:
    candidates: list[Path] = []
    for key in ("golden_input_dir", "raw_input_dir"):
        if key in config.paths and config.path(key).is_dir():
            candidates.extend(sorted(config.path(key).glob("*.txt"), key=lambda item: _natural_stem_key(item.stem)))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if len(seen) <= start_index:
            continue
        unique.append(path)
        if len(unique) >= max_files:
            break
    return unique


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