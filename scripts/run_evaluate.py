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
from src.evaluation import GoldenEvaluator, write_evaluation_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate prediction JSON files against golden annotations.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--input-dir", required=True, help="Directory containing raw .txt files.")
    parser.add_argument("--gold-dir", required=True, help="Directory containing gold .json files.")
    parser.add_argument("--pred-dir", required=True, help="Directory containing prediction .json files.")
    parser.add_argument("--report-dir", required=True, help="Directory to write evaluation reports.")
    parser.add_argument("--expected-count", type=int, default=None, help="Expected number of input files.")
    parser.add_argument("--relaxed-iou-threshold", type=float, default=None, help="Override relaxed IoU threshold.")
    parser.add_argument("--relaxed-containment-threshold", type=float, default=None, help="Override relaxed containment threshold.")
    parser.add_argument("--allow-validation-errors", action="store_true", help="Do not fail when gold/pred validation errors are present.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    evaluation_cfg = dict(config.raw.get("evaluation", {}))
    matching_cfg = dict(evaluation_cfg.get("matching", {}))
    if args.relaxed_iou_threshold is not None:
        matching_cfg["relaxed_iou_threshold"] = args.relaxed_iou_threshold
    if args.relaxed_containment_threshold is not None:
        matching_cfg["relaxed_containment_threshold"] = args.relaxed_containment_threshold
    evaluation_cfg["matching"] = matching_cfg
    validation_cfg = dict(evaluation_cfg.get("validation", {}))
    if args.allow_validation_errors:
        validation_cfg["fail_on_validation_error"] = False
    evaluation_cfg["validation"] = validation_cfg

    evaluator = GoldenEvaluator(evaluation_cfg, validation_config=config.raw.get("prediction_validation", {}))
    report = evaluator.evaluate_directories(
        input_dir=args.input_dir,
        gold_dir=args.gold_dir,
        pred_dir=args.pred_dir,
        expected_count=args.expected_count,
    )
    write_evaluation_report(report, args.report_dir)

    print("Golden evaluation completed.")
    print(f"files_evaluated: {report.files_evaluated}")
    print(f"gold_entities: {report.gold_entities}")
    print(f"pred_entities: {report.pred_entities}")
    print(f"exact_tp: {report.overall_exact.tp}")
    print(f"exact_fp: {report.overall_exact.fp}")
    print(f"exact_fn: {report.overall_exact.fn}")
    print(f"exact_precision: {report.overall_exact.precision:.4f}")
    print(f"exact_recall: {report.overall_exact.recall:.4f}")
    print(f"exact_f1: {report.overall_exact.f1:.4f}")
    print(f"relaxed_tp: {report.overall_relaxed.tp}")
    print(f"relaxed_fp: {report.overall_relaxed.fp}")
    print(f"relaxed_fn: {report.overall_relaxed.fn}")
    print(f"relaxed_precision: {report.overall_relaxed.precision:.4f}")
    print(f"relaxed_recall: {report.overall_relaxed.recall:.4f}")
    print(f"relaxed_f1: {report.overall_relaxed.f1:.4f}")
    print(f"assertion_exact_match_rate: {report.assertion_metrics.get('exact_set_match_rate', 0.0):.4f}")
    print(f"candidate_hit_rate: {report.candidate_metrics.get('hit_rate', 0.0):.4f}")
    print(f"span_mismatch_count: {report.error_category_counts.get('span_mismatch', 0)}")
    print(f"type_mismatch_count: {report.error_category_counts.get('type_mismatch', 0)}")
    print(f"assertion_mismatch_count: {report.error_category_counts.get('assertion_mismatch', 0)}")
    print(f"candidate_mismatch_count: {report.error_category_counts.get('candidate_mismatch', 0)}")
    print(f"report_dir: {args.report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())