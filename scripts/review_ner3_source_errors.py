from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.io_utils import read_json, write_json
from src.ner.candidate_ledger import read_candidate_ledger


ERROR_FILES = {
    "false_positive": "false_positives.jsonl",
    "false_negative": "false_negatives.jsonl",
    "boundary": "span_mismatches.jsonl",
    "type_conflict": "type_mismatches.jsonl",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the NER-3 source-specific error review queue.")
    parser.add_argument("--output-root", default="outputs/experiments/ner3")
    parser.add_argument("--output-dir", default="outputs/reports/ner3_source_error_review")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root, target = Path(args.output_root), Path(args.output_dir)
    complementarity = read_json(root / "complementarity.json")
    source_counts = complementarity.get("aggregate", {}).get("by_source", {})
    rows, counts = build_review_rows(root, checkpoints=("A", "B", "C", "D"))
    target.mkdir(parents=True, exist_ok=True)
    _write_jsonl(target / "source_error_queue.jsonl", rows)
    summary = {
        "schema_version": "ner3-source-error-review-v1", "reviewed": False,
        "row_count": len(rows), "counts": counts, "source_complementarity": source_counts,
        "review_instructions": [
            "Review A/B/C/D errors without changing the development gold labels.",
            "Attribute a prediction only from recorded source_candidates; do not infer a source from text.",
            "C is diagnostic-only. A promotion decision for D remains manual and belongs to the next milestone gate.",
        ],
    }
    write_json(target / "source_error_summary.json", summary)
    print(json.dumps({"rows": len(rows), "reviewed": False}, ensure_ascii=False))
    return 0


def build_review_rows(root: Path, *, checkpoints: Sequence[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counts: Counter[tuple[str, str, str, str]] = Counter()
    for checkpoint in checkpoints:
        extraction_evaluation = root / checkpoint / "evaluation" / "extraction_only"
        evaluation = extraction_evaluation if extraction_evaluation.is_dir() else root / checkpoint / "evaluation"
        for category, name in ERROR_FILES.items():
            for row in _read_jsonl(evaluation / name):
                entity = row.get("pred") if isinstance(row.get("pred"), Mapping) else row
                entity_type = str(entity.get("type", "UNKNOWN")) if isinstance(entity, Mapping) else "UNKNOWN"
                sources = _sources(row)
                if not sources:
                    sources = _trace_sources(root, checkpoint, row)
                if not sources:
                    sources = _ledger_sources(root, row)
                if not sources:
                    sources = ["gold_unattributed" if category == "false_negative" else "unattributed"]
                enriched = dict(row)
                enriched.update({"checkpoint": checkpoint, "error_category": category, "entity_type": entity_type, "sources": sources})
                rows.append(enriched)
                for source in sources:
                    counts[(checkpoint, source, entity_type, category)] += 1
    rows.sort(key=lambda row: (row["checkpoint"], row["error_category"], str(row.get("file_id", "")), json.dumps(row, ensure_ascii=False, sort_keys=True)))
    nested: dict[str, Any] = {}
    for (checkpoint, source, entity_type, category), count in sorted(counts.items()):
        nested.setdefault(checkpoint, {}).setdefault(source, {}).setdefault(entity_type, {})[category] = count
    return rows, nested


def _sources(row: Mapping[str, Any]) -> list[str]:
    provenance = row.get("prediction_provenance", row.get("provenance", {}))
    if not isinstance(provenance, Mapping):
        return []
    candidates = provenance.get("source_candidates", [])
    values = {str(item.get("source")) for item in candidates if isinstance(item, Mapping) and item.get("source")}
    chosen = provenance.get("chosen_source")
    if chosen:
        values.add(str(chosen))
    return sorted(values)


def _ledger_sources(root: Path, row: Mapping[str, Any]) -> list[str]:
    file_id = str(row.get("file_id", ""))
    pred = row.get("pred") if isinstance(row.get("pred"), Mapping) else row
    position = pred.get("position", []) if isinstance(pred, Mapping) else []
    entity_type = str(pred.get("type", "")) if isinstance(pred, Mapping) else ""
    manifest_path = root / "candidate_ledger_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    ledger_dir = Path(str(manifest.get("ledger_dir", root / "candidate_ledgers")))
    ledger_path = ledger_dir / f"{file_id}.json"
    input_path = root / "corpus" / "input" / f"{file_id}.txt"
    if not ledger_path.is_file() or not input_path.is_file() or not isinstance(position, list) or len(position) != 2:
        return []
    _, candidates = read_candidate_ledger(ledger_path, input_path.read_text(encoding="utf-8"))
    return sorted({
        candidate.source for candidate in candidates
        if [candidate.start, candidate.end] == position and str(candidate.raw_type) == entity_type
    })


def _trace_sources(root: Path, checkpoint: str, row: Mapping[str, Any]) -> list[str]:
    file_id = str(row.get("file_id", ""))
    pred = row.get("pred") if isinstance(row.get("pred"), Mapping) else row
    position = pred.get("position", []) if isinstance(pred, Mapping) else []
    entity_type = str(pred.get("type", "")) if isinstance(pred, Mapping) else ""
    trace_path = root / checkpoint / "source_trace" / f"{file_id}.json"
    if not trace_path.is_file() or not isinstance(position, list) or len(position) != 2:
        return []
    trace = read_json(trace_path)
    for entity in trace.get("entities", []) if isinstance(trace, Mapping) else []:
        if entity.get("position") != position or str(entity.get("type", "")) != entity_type:
            continue
        provenance = entity.get("provenance", {})
        rows = provenance.get("source_candidates", []) if isinstance(provenance, Mapping) else []
        sources = {str(item.get("source")) for item in rows if isinstance(item, Mapping) and item.get("source")}
        chosen = provenance.get("chosen_source") if isinstance(provenance, Mapping) else None
        if chosen:
            sources.add(str(chosen))
        return sorted(sources)
    return []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    output: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                output.append(value)
    return output


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())