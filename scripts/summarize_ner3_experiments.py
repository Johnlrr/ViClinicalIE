from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_ner3_experiments import validate_checkpoint_plan
from src.config import load_yaml
from src.io_utils import read_json, write_json
from src.ner.experiment_registry import file_hash


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize NER-3 A/B/C/D without automatically promoting fusion.")
    parser.add_argument("--output-root", default="outputs/experiments/ner3")
    parser.add_argument("--matrix", default="configs/ner3/experiment_matrix.yaml")
    parser.add_argument("--policy", default="configs/ner3/selection_policy.yaml")
    parser.add_argument("--summary-dir", default="outputs/reports/ner3_experiment_summary")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    matrix_path, policy_path = Path(args.matrix), Path(args.policy)
    matrix, policy = load_yaml(matrix_path), load_yaml(policy_path)
    specs = validate_checkpoint_plan(matrix)
    manifests = collect_manifests(Path(args.output_root), specs)
    summary = summarize(manifests, policy)
    summary.update({"matrix_hash": file_hash(matrix_path), "policy_hash": file_hash(policy_path)})
    target = Path(args.summary_dir)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "summary.json", summary)
    _write_csv(target / "summary.csv", summary["checkpoints"])
    print(f"NER-3 checkpoints summarized: {len(summary['checkpoints'])}; review_ready={summary['review_ready']}")
    return 0


def collect_manifests(root: Path, specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for spec in specs:
        path = root / str(spec["id"]) / "run_manifest.json"
        if not path.is_file():
            raise FileNotFoundError(f"Missing NER-3 checkpoint {spec['id']}: {path}")
        value = read_json(path)
        if not isinstance(value, dict) or value.get("checkpoint") != spec["id"] or value.get("mode") != spec["mode"]:
            raise ValueError(f"Invalid manifest for checkpoint {spec['id']}")
        output.append(value)
    return output


def summarize(manifests: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    required = [str(value) for value in policy.get("required_checkpoints", ["A", "B", "C", "D"])]
    if [str(row.get("checkpoint")) for row in manifests] != required:
        raise ValueError("NER-3 summary requires completed A/B/C/D checkpoints in order")
    ledger_hashes = {str(row.get("ledger_manifest_hash", "")) for row in manifests}
    shared_ledger = len(ledger_hashes) == 1 and "" not in ledger_hashes
    rows: list[dict[str, Any]] = []
    gates_pass = shared_ledger or not bool(policy.get("require_shared_candidate_ledger", True))
    density_max = float(policy.get("regression_budget", {}).get("density_ratio_max", float("inf")))
    for manifest in manifests:
        metrics = manifest.get("metrics", {})
        exact, relaxed = metrics.get("exact", {}), metrics.get("relaxed", {})
        validation_errors = int(manifest.get("validation_error_count", 1))
        evidence_errors = int(manifest.get("ledger_evidence_error_count", 1))
        duplicate_count = int(manifest.get("duplicate_exact_span_count", 1))
        density_ratio = manifest.get("density", {}).get("density_ratio")
        density_safe = density_ratio is not None and float(density_ratio) <= density_max
        safe = (
            (validation_errors == 0 or not policy.get("require_zero_validation_errors", True))
            and (evidence_errors == 0 or not policy.get("require_zero_evidence_errors", True))
            and (duplicate_count == 0 or not policy.get("require_zero_duplicate_exact_spans", True))
            and density_safe
        )
        gates_pass = gates_pass and safe
        rows.append({
            "checkpoint": manifest["checkpoint"], "name": manifest.get("name"), "mode": manifest["mode"],
            "diagnostic_only": bool(manifest.get("diagnostic_only", False)),
            "files": int(metrics.get("files_evaluated", 0)), "pred_entities": int(metrics.get("pred_entities", 0)),
            "exact_precision": float(exact.get("precision", 0.0)), "exact_recall": float(exact.get("recall", 0.0)),
            "exact_f1": float(exact.get("f1", 0.0)), "relaxed_f1": float(relaxed.get("f1", 0.0)),
            "end_to_end_final_score": float(manifest.get("official_like_final_score", 0.0)),
            "density_ratio": density_ratio, "density_safe": density_safe,
            "validation_errors": validation_errors, "evidence_errors": evidence_errors,
            "duplicate_exact_spans": duplicate_count, "safe": safe,
            "structured_anchor_events": int(manifest.get("structured_anchor_event_count", 0)),
            "gliner_unconfirmed_total": int(manifest.get("gliner_unconfirmed", {}).get("total", 0)),
            "gliner_unconfirmed_survived": int(manifest.get("gliner_unconfirmed", {}).get("survived_exact", 0)),
        })
    d_row = rows[-1]
    unconfirmed_preserved = d_row["gliner_unconfirmed_survived"] == d_row["gliner_unconfirmed_total"]
    gates_pass = gates_pass and unconfirmed_preserved
    required_files = int(policy.get("required_development_files", 12))
    full_development_complete = all(row["files"] == required_files for row in rows)
    review_ready = gates_pass and full_development_complete and bool(policy.get("promotion", {}).get("requires_manual_source_error_review", True))
    return {
        "schema_version": "ner3-summary-v1", "shared_candidate_ledger": shared_ledger,
        "safety_gates_pass": gates_pass, "gliner_unconfirmed_preserved": unconfirmed_preserved,
        "required_development_files": required_files, "full_development_complete": full_development_complete,
        "review_ready": review_ready,
        "promotion_decision": "manual_review_required" if review_ready else "blocked",
        "automatic_promotion": False, "checkpoints": rows,
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = [
        "checkpoint", "name", "mode", "diagnostic_only", "files", "pred_entities",
        "exact_precision", "exact_recall", "exact_f1", "relaxed_f1", "validation_errors",
        "end_to_end_final_score", "density_ratio", "density_safe",
        "evidence_errors", "duplicate_exact_spans", "safe", "structured_anchor_events",
        "gliner_unconfirmed_total", "gliner_unconfirmed_survived",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column) for column in columns} for row in rows)


if __name__ == "__main__":
    raise SystemExit(main())
