from __future__ import annotations

import argparse
import csv
import json
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

from src.config import load_config
from src.io_utils import read_json, write_json, write_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze ICD/RxNorm candidate mapping errors from an evaluation report.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--eval-report-dir", required=True, help="Directory containing run_evaluate.py output files.")
    parser.add_argument("--pred-dir", required=True, help="Prediction directory used for the evaluation.")
    parser.add_argument("--gold-dir", required=True, help="Gold directory used for the evaluation.")
    parser.add_argument("--output-dir", default="outputs/reports/phase15_candidate_analysis", help="Directory for candidate analysis artifacts.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    eval_dir = _resolve(args.eval_report_dir)
    pred_dir = _resolve(args.pred_dir)
    gold_dir = _resolve(args.gold_dir)
    output_dir = _resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mismatches = _read_jsonl(eval_dir / "candidate_mismatches.jsonl")
    summary = read_json(eval_dir / "evaluation_summary.json") if (eval_dir / "evaluation_summary.json").is_file() else {}
    no_candidate_rows = _collect_no_candidate_rows(pred_dir, gold_dir)

    _write_csv(output_dir / "candidate_errors.csv", mismatches)
    _write_csv(output_dir / "no_candidate_entities.csv", no_candidate_rows)
    _write_csv(output_dir / "wrong_candidate_entities.csv", [row for row in mismatches if row.get("subcategory") == "wrong_candidate"])
    _write_csv(output_dir / "missing_candidate_entities.csv", [row for row in mismatches if row.get("subcategory") == "missing_candidate"])
    _write_csv(output_dir / "drug_strength_errors.csv", _drug_rows(mismatches))
    _write_csv(output_dir / "icd_alias_gaps.csv", _icd_rows(mismatches))

    counts = Counter(str(row.get("subcategory", "unknown")) for row in mismatches)
    by_type = Counter(str(row.get("gold", {}).get("type") or row.get("pred", {}).get("type") or "unknown") for row in mismatches)
    analysis = {
        "eval_report_dir": str(eval_dir),
        "pred_dir": str(pred_dir),
        "gold_dir": str(gold_dir),
        "phase": config.raw.get("project", {}).get("phase"),
        "candidate_metrics": summary.get("candidates", {}),
        "candidate_mismatch_count": len(mismatches),
        "mismatch_counts": dict(sorted(counts.items())),
        "mismatch_by_type": dict(sorted(by_type.items())),
        "pred_linkable_entities_without_candidates": len(no_candidate_rows),
    }
    write_json(output_dir / "summary.json", analysis)
    write_text(output_dir / "summary.md", _summary_md(analysis, mismatches, no_candidate_rows))

    print("Candidate mapping analysis completed.")
    print(f"candidate_mismatch_count: {len(mismatches)}")
    print(f"pred_linkable_entities_without_candidates: {len(no_candidate_rows)}")
    print(f"output_dir: {output_dir}")
    return 0


def _collect_no_candidate_rows(pred_dir: Path, gold_dir: Path) -> list[dict[str, Any]]:
    del gold_dir  # reserved for later gold-only alias-gap analysis
    rows: list[dict[str, Any]] = []
    for path in sorted(pred_dir.glob("*.json"), key=lambda item: _natural_key(item.stem)):
        records = read_json(path)
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            entity_type = str(record.get("type", ""))
            if entity_type not in {"CHẨN_ĐOÁN", "THUỐC"}:
                continue
            if record.get("candidates"):
                continue
            rows.append(
                {
                    "file_id": path.stem,
                    "index": index,
                    "text": record.get("text", ""),
                    "position": record.get("position", []),
                    "type": entity_type,
                    "assertions": record.get("assertions", []),
                    "candidates": record.get("candidates", []),
                }
            )
    return rows


def _drug_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("gold", {}).get("type") or row.get("pred", {}).get("type")) == "THUỐC"]


def _icd_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("gold", {}).get("type") or row.get("pred", {}).get("type")) == "CHẨN_ĐOÁN"]


def _summary_md(analysis: dict[str, Any], mismatches: list[dict[str, Any]], no_candidate_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Phase 15 candidate mapping analysis",
        "",
        f"- phase: `{analysis.get('phase')}`",
        f"- candidate_mismatch_count: {analysis.get('candidate_mismatch_count')}",
        f"- pred_linkable_entities_without_candidates: {analysis.get('pred_linkable_entities_without_candidates')}",
        f"- candidate_hit_rate: {analysis.get('candidate_metrics', {}).get('hit_rate', 0.0)}",
        "",
        "## Mismatch counts",
        "",
    ]
    for key, value in analysis.get("mismatch_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Candidate mismatch samples", ""])
    for row in mismatches[:20]:
        pred = row.get("pred", {})
        gold = row.get("gold", {})
        lines.append(
            f"- file `{row.get('file_id')}` {row.get('subcategory')}: "
            f"pred `{pred.get('text')}` {pred.get('candidates')} vs gold {gold.get('candidates')}"
        )
    lines.extend(["", "## No-candidate samples", ""])
    for row in no_candidate_rows[:20]:
        lines.append(f"- file `{row.get('file_id')}` {row.get('type')}: `{row.get('text')}`")
    return "\n".join(lines) + "\n"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = _fieldnames(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cell(row.get(key)) for key in fieldnames})


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    preferred = ["file_id", "category", "subcategory", "pred", "gold", "missing_candidates", "extra_candidates", "intersection"]
    keys: list[str] = []
    for key in preferred:
        if any(key in row for row in rows):
            keys.append(key)
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return keys or preferred


def _cell(value: Any) -> str:
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def _natural_key(stem: str) -> tuple[int, int | str]:
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
