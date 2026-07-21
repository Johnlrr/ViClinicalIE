from __future__ import annotations

import csv
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.evaluation.error_analysis import find_span_mismatches, find_type_mismatches
from src.evaluation.metrics import (
    aggregate_counts,
    aggregate_type_counts,
    compute_assertion_metrics,
    compute_candidate_metrics,
    counts_by_type,
    counts_from_match_result,
)
from src.evaluation.models import EvalEntity, EntityPair, EvaluationFileResult, EvaluationReport, PRFCounts
from src.evaluation.span_matcher import exact_match_entities, relaxed_match_entities
from src.io_utils import append_jsonl, read_json, read_text, write_json, write_text
from src.postprocess.policies import ASSERTION_ORDER, dedupe_stable
from src.validation.prediction_schema import validate_prediction_records


class GoldenEvaluator:
    def __init__(self, config: Mapping[str, Any] | None = None, validation_config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.validation_config = dict(validation_config or {})
        matching_cfg = dict(self.config.get("matching", {}))
        attr_cfg = dict(self.config.get("attributes", {}))
        reports_cfg = dict(self.config.get("reports", {}))
        validation_cfg = dict(self.config.get("validation", {}))
        self.relaxed_iou_threshold = float(matching_cfg.get("relaxed_iou_threshold", 0.50))
        self.relaxed_containment_threshold = float(matching_cfg.get("relaxed_containment_threshold", 0.80))
        self.type_mismatch_iou_threshold = float(matching_cfg.get("type_mismatch_iou_threshold", 0.50))
        self.type_mismatch_containment_threshold = float(matching_cfg.get("type_mismatch_containment_threshold", 0.80))
        self.skip_empty_gold_candidates = bool(attr_cfg.get("skip_empty_gold_candidates", True))
        self.context_window = int(reports_cfg.get("context_window_chars", 120))
        self.max_samples_per_category = int(reports_cfg.get("max_samples_per_category", 50))
        self.fail_on_validation_error = bool(validation_cfg.get("fail_on_validation_error", True))

    def evaluate_records(
        self,
        *,
        file_id: str,
        raw_text: str,
        gold_records: list[dict[str, Any]],
        pred_records: list[dict[str, Any]],
    ) -> EvaluationFileResult:
        self._validate_records_or_raise(gold_records, raw_text, file_name=f"{file_id}.gold.json")
        self._validate_records_or_raise(pred_records, raw_text, file_name=f"{file_id}.pred.json")
        golds = records_to_eval_entities(file_id, gold_records)
        predictions = records_to_eval_entities(file_id, pred_records)

        exact_pairs, exact_unmatched_pred, exact_unmatched_gold = exact_match_entities(predictions, golds)
        relaxed_pairs, relaxed_unmatched_pred, relaxed_unmatched_gold = relaxed_match_entities(
            predictions,
            golds,
            iou_threshold=self.relaxed_iou_threshold,
            containment_threshold=self.relaxed_containment_threshold,
        )
        assertion_metrics = compute_assertion_metrics(exact_pairs)
        candidate_metrics = compute_candidate_metrics(exact_pairs, skip_empty_gold_candidates=self.skip_empty_gold_candidates)
        span_mismatches = find_span_mismatches(
            exact_unmatched_pred,
            exact_unmatched_gold,
            iou_threshold=self.relaxed_iou_threshold,
            containment_threshold=self.relaxed_containment_threshold,
            raw_text=raw_text,
            context_window=self.context_window,
        )
        type_mismatches = find_type_mismatches(
            exact_unmatched_pred,
            exact_unmatched_gold,
            iou_threshold=self.type_mismatch_iou_threshold,
            containment_threshold=self.type_mismatch_containment_threshold,
            raw_text=raw_text,
            context_window=self.context_window,
        )
        return EvaluationFileResult(
            file_id=file_id,
            gold_count=len(golds),
            pred_count=len(predictions),
            exact_counts=counts_from_match_result(exact_pairs, exact_unmatched_pred, exact_unmatched_gold),
            relaxed_counts=counts_from_match_result(relaxed_pairs, relaxed_unmatched_pred, relaxed_unmatched_gold),
            exact_pairs=exact_pairs,
            relaxed_pairs=relaxed_pairs,
            false_positives=exact_unmatched_pred,
            false_negatives=exact_unmatched_gold,
            span_mismatches=span_mismatches,
            type_mismatches=type_mismatches,
            assertion_mismatches=assertion_metrics["mismatches"],
            candidate_mismatches=candidate_metrics["mismatches"],
        )

    def evaluate_directories(
        self,
        *,
        input_dir: str | Path,
        gold_dir: str | Path,
        pred_dir: str | Path,
        expected_count: int | None = None,
    ) -> EvaluationReport:
        input_path = Path(input_dir)
        gold_path = Path(gold_dir)
        pred_path = Path(pred_dir)
        input_files = sorted(input_path.glob("*.txt"), key=lambda item: _natural_stem_key(item.stem))
        if expected_count is not None and len(input_files) != expected_count:
            raise ValueError(f"Input file count mismatch: expected {expected_count}, got {len(input_files)}")
        file_results: list[EvaluationFileResult] = []
        exact_type_counts: list[dict[str, PRFCounts]] = []
        relaxed_type_counts: list[dict[str, PRFCounts]] = []
        all_exact_pairs: list[EntityPair] = []
        for input_file in input_files:
            file_id = input_file.stem
            gold_file = gold_path / f"{file_id}.json"
            pred_file = pred_path / f"{file_id}.json"
            if not gold_file.is_file():
                raise FileNotFoundError(f"Missing gold file for {file_id}: {gold_file}")
            if not pred_file.is_file():
                raise FileNotFoundError(f"Missing prediction file for {file_id}: {pred_file}")
            raw_text = read_text(input_file)
            gold_records = read_json(gold_file)
            pred_records = read_json(pred_file)
            result = self.evaluate_records(file_id=file_id, raw_text=raw_text, gold_records=gold_records, pred_records=pred_records)
            file_results.append(result)
            predictions = records_to_eval_entities(file_id, pred_records)
            golds = records_to_eval_entities(file_id, gold_records)
            exact_type_counts.append(counts_by_type(predictions, golds, result.exact_pairs))
            relaxed_type_counts.append(counts_by_type(predictions, golds, result.relaxed_pairs))
            all_exact_pairs.extend(result.exact_pairs)

        assertion_metrics = compute_assertion_metrics(all_exact_pairs)
        candidate_metrics = compute_candidate_metrics(all_exact_pairs, skip_empty_gold_candidates=self.skip_empty_gold_candidates)
        return EvaluationReport(
            files=file_results,
            overall_exact=aggregate_counts(file_results, "exact_counts"),
            overall_relaxed=aggregate_counts(file_results, "relaxed_counts"),
            by_type_exact=aggregate_type_counts(exact_type_counts),
            by_type_relaxed=aggregate_type_counts(relaxed_type_counts),
            assertion_metrics=_strip_mismatch_records(assertion_metrics),
            candidate_metrics=_strip_mismatch_records(candidate_metrics),
            error_category_counts=_error_category_counts(file_results),
            type_confusion=_type_confusion(file_results),
            boundary_error_counts=_boundary_error_counts(file_results),
        )

    def _validate_records_or_raise(self, records: Any, raw_text: str, *, file_name: str) -> None:
        report = validate_prediction_records(records, raw_text, file_name=file_name, config=self.validation_config)
        if self.fail_on_validation_error and report.error_count:
            raise ValueError(f"Validation failed for {file_name}: {report.issue_counts_by_code(level='error')}")


def records_to_eval_entities(file_id: str, records: list[dict[str, Any]]) -> list[EvalEntity]:
    entities: list[EvalEntity] = []
    for index, record in enumerate(records):
        position = record.get("position", [0, 0])
        assertions = tuple(_ordered_dedupe_assertions(record.get("assertions", [])))
        candidates = tuple(dedupe_stable([str(candidate) for candidate in record.get("candidates", [])]))
        entities.append(
            EvalEntity(
                file_id=file_id,
                text=str(record.get("text", "")),
                start=int(position[0]),
                end=int(position[1]),
                type=str(record.get("type", "")),
                assertions=assertions,
                candidates=candidates,
                index=index,
            )
        )
    return entities


def write_evaluation_report(report: EvaluationReport, report_dir: str | Path) -> None:
    target = Path(report_dir)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "evaluation_summary.json", report.to_dict())
    _write_per_file_metrics(report, target / "per_file_metrics.csv")
    _write_per_type_metrics(report, target / "per_type_metrics.csv")
    _write_confusion_matrix(report, target / "type_confusion_matrix.csv")
    _write_jsonl(target / "true_positives.jsonl", [pair.to_dict() for file in report.files for pair in file.exact_pairs])
    _write_jsonl(target / "false_positives.jsonl", [_fp_to_dict(entity) for file in report.files for entity in file.false_positives])
    _write_jsonl(target / "false_negatives.jsonl", [_fn_to_dict(entity) for file in report.files for entity in file.false_negatives])
    _write_jsonl(target / "span_mismatches.jsonl", [record for file in report.files for record in file.span_mismatches])
    _write_jsonl(target / "type_mismatches.jsonl", [record for file in report.files for record in file.type_mismatches])
    _write_jsonl(target / "assertion_mismatches.jsonl", [record for file in report.files for record in file.assertion_mismatches])
    _write_jsonl(target / "candidate_mismatches.jsonl", [record for file in report.files for record in file.candidate_mismatches])
    error_cases = []
    for file in report.files:
        error_cases.extend(_fp_to_dict(entity) for entity in file.false_positives)
        error_cases.extend(_fn_to_dict(entity) for entity in file.false_negatives)
        error_cases.extend(file.span_mismatches)
        error_cases.extend(file.type_mismatches)
        error_cases.extend(file.assertion_mismatches)
        error_cases.extend(file.candidate_mismatches)
    _write_jsonl(target / "error_cases.jsonl", error_cases)
    _write_samples_md(report, target / "samples.md")


def _write_per_file_metrics(report: EvaluationReport, path: Path) -> None:
    rows = []
    for file in report.files:
        rows.append(
            {
                "file_id": file.file_id,
                "gold_count": file.gold_count,
                "pred_count": file.pred_count,
                "exact_tp": file.exact_counts.tp,
                "exact_fp": file.exact_counts.fp,
                "exact_fn": file.exact_counts.fn,
                "exact_precision": file.exact_counts.precision,
                "exact_recall": file.exact_counts.recall,
                "exact_f1": file.exact_counts.f1,
                "relaxed_tp": file.relaxed_counts.tp,
                "relaxed_fp": file.relaxed_counts.fp,
                "relaxed_fn": file.relaxed_counts.fn,
                "relaxed_precision": file.relaxed_counts.precision,
                "relaxed_recall": file.relaxed_counts.recall,
                "relaxed_f1": file.relaxed_counts.f1,
                "span_mismatch_count": len(file.span_mismatches),
                "type_mismatch_count": len(file.type_mismatches),
                "assertion_mismatch_count": len(file.assertion_mismatches),
                "candidate_mismatch_count": len(file.candidate_mismatches),
            }
        )
    _write_csv(path, rows)


def _write_per_type_metrics(report: EvaluationReport, path: Path) -> None:
    rows = []
    entity_types = sorted(set(report.by_type_exact) | set(report.by_type_relaxed))
    for entity_type in entity_types:
        exact = report.by_type_exact.get(entity_type, PRFCounts())
        relaxed = report.by_type_relaxed.get(entity_type, PRFCounts())
        rows.append(
            {
                "type": entity_type,
                "exact_tp": exact.tp,
                "exact_fp": exact.fp,
                "exact_fn": exact.fn,
                "exact_precision": exact.precision,
                "exact_recall": exact.recall,
                "exact_f1": exact.f1,
                "relaxed_tp": relaxed.tp,
                "relaxed_fp": relaxed.fp,
                "relaxed_fn": relaxed.fn,
                "relaxed_precision": relaxed.precision,
                "relaxed_recall": relaxed.recall,
                "relaxed_f1": relaxed.f1,
            }
        )
    _write_csv(path, rows)


def _write_confusion_matrix(report: EvaluationReport, path: Path) -> None:
    entity_types = sorted(set(report.type_confusion) | {pred for row in report.type_confusion.values() for pred in row})
    rows = []
    for gold_type in entity_types:
        row: dict[str, Any] = {"gold_type": gold_type}
        row.update({pred_type: report.type_confusion.get(gold_type, {}).get(pred_type, 0) for pred_type in entity_types})
        rows.append(row)
    _write_csv(path, rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        write_text(path, "")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    write_text(path, "")
    for record in records:
        append_jsonl(path, record)


def _write_samples_md(report: EvaluationReport, path: Path) -> None:
    lines = ["# Phase 12 Evaluation Samples", "", "## Summary", "", f"- files_evaluated: {report.files_evaluated}", f"- gold_entities: {report.gold_entities}", f"- pred_entities: {report.pred_entities}", f"- exact_f1: {report.overall_exact.f1:.4f}", f"- relaxed_f1: {report.overall_relaxed.f1:.4f}", ""]
    sections = [
        ("False positives", [_fp_to_dict(entity) for file in report.files for entity in file.false_positives]),
        ("False negatives", [_fn_to_dict(entity) for file in report.files for entity in file.false_negatives]),
        ("Span mismatches", [record for file in report.files for record in file.span_mismatches]),
        ("Type mismatches", [record for file in report.files for record in file.type_mismatches]),
        ("Assertion mismatches", [record for file in report.files for record in file.assertion_mismatches]),
        ("Candidate mismatches", [record for file in report.files for record in file.candidate_mismatches]),
    ]
    for title, records in sections:
        lines.extend([f"## {title}", ""])
        for record in records[:50]:
            lines.append(f"- `{record.get('file_id')}` {record.get('category')} {record.get('subcategory', '')}: {record}")
        lines.append("")
    write_text(path, "\n".join(lines))


def _fp_to_dict(entity: EvalEntity) -> dict[str, Any]:
    return {"file_id": entity.file_id, "category": "false_positive", "pred": entity.to_dict()}


def _fn_to_dict(entity: EvalEntity) -> dict[str, Any]:
    return {"file_id": entity.file_id, "category": "false_negative", "gold": entity.to_dict()}


def _strip_mismatch_records(metrics: dict[str, Any]) -> dict[str, Any]:
    clean = dict(metrics)
    clean.pop("mismatches", None)
    return clean


def _error_category_counts(file_results: list[EvaluationFileResult]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for file in file_results:
        counter["false_positive"] += len(file.false_positives)
        counter["false_negative"] += len(file.false_negatives)
        counter["span_mismatch"] += len(file.span_mismatches)
        counter["type_mismatch"] += len(file.type_mismatches)
        counter["assertion_mismatch"] += len(file.assertion_mismatches)
        counter["candidate_mismatch"] += len(file.candidate_mismatches)
    return dict(counter)


def _type_confusion(file_results: list[EvaluationFileResult]) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for file in file_results:
        for record in file.type_mismatches:
            gold_type = str(record.get("gold", {}).get("type", "UNKNOWN"))
            pred_type = str(record.get("pred", {}).get("type", "UNKNOWN"))
            matrix[gold_type][pred_type] += 1
    return {gold: dict(sorted(row.items())) for gold, row in sorted(matrix.items())}


def _boundary_error_counts(file_results: list[EvaluationFileResult]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for file in file_results:
        counter.update(str(record.get("subcategory", "unknown")) for record in file.span_mismatches)
    return dict(sorted(counter.items()))


def _ordered_dedupe_assertions(assertions: Any) -> list[str]:
    if not isinstance(assertions, list):
        return []
    seen = set()
    output: list[str] = []
    for assertion in ASSERTION_ORDER:
        if assertion in assertions and assertion not in seen:
            output.append(assertion)
            seen.add(assertion)
    for assertion in assertions:
        if not isinstance(assertion, str) or assertion in seen:
            continue
        output.append(assertion)
        seen.add(assertion)
    return output


def _natural_stem_key(stem: str) -> tuple[int, int | str]:
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)