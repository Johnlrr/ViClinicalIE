from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config, load_yaml
from src.evaluation import GoldenEvaluator, write_evaluation_report
from src.formatting.json_formatter import write_prediction_json
from src.io_utils import write_json
from src.pipeline import ClinicalIEPipeline


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Benchmark GLiNER extraction through the repository ClinicalIEPipeline.")
    parser.add_argument("--config", default="configs/gliner_zero_shot.yaml")
    parser.add_argument("--split-config", default="configs/splits_v2.yaml")
    parser.add_argument("--split", choices=("development", "calibration", "lockbox", "all"), default="development")
    parser.add_argument("--input-dir", default="data/golden/input")
    parser.add_argument("--gold-dir", default="data/golden/gold")
    parser.add_argument("--output-dir", default="outputs/predictions/v2_ner1_gliner_reproduction")
    parser.add_argument("--report-dir", default="outputs/reports/v2_ner1_gliner_reproduction")
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    split_config = load_yaml(args.split_config)
    ids = _split_ids(split_config, args.split)
    if args.max_files is not None:
        ids = ids[: args.max_files]
    input_dir, gold_dir = Path(args.input_dir), Path(args.gold_dir)
    output_dir, report_dir = Path(args.output_dir), Path(args.report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.json"):
        stale.unlink()

    tracemalloc.start()
    start_time = time.perf_counter()
    pipeline = ClinicalIEPipeline(config, enable_sparse_retrieval=False, ner_only=True)
    counts: Counter[str] = Counter()
    per_file: list[dict] = []
    debug_dir = report_dir / "debug_entities"
    debug_dir.mkdir(parents=True, exist_ok=True)
    for stale in debug_dir.glob("*.json"):
        stale.unlink()
    for file_id in ids:
        path = input_dir / f"{file_id}.txt"
        file_start = time.perf_counter()
        result = pipeline.process_file(path)
        write_prediction_json(result.records, output_dir / f"{file_id}.json", config.raw.get("output_format", {}))
        write_json(debug_dir / f"{file_id}.json", [
            {
                "text": entity.text,
                "position": entity.position,
                "type": str(entity.type),
                "confidence": entity.confidence,
                "provenance": entity.provenance,
            }
            for entity in result.entities
        ])
        elapsed = time.perf_counter() - file_start
        counts.update(result.entities_by_type)
        per_file.append({"file_id": file_id, "seconds": elapsed, "entities": len(result.entities), "counters": result.counters})
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    evaluator = GoldenEvaluator(config.raw.get("evaluation", {}), validation_config=config.raw.get("prediction_validation", {}))
    if len(ids) != len(list(input_dir.glob("*.txt"))):
        selected_input = report_dir / "selected_input"
        selected_gold = report_dir / "selected_gold"
        selected_input.mkdir(parents=True, exist_ok=True)
        selected_gold.mkdir(parents=True, exist_ok=True)
        for stale in [*selected_input.glob("*"), *selected_gold.glob("*")]:
            stale.unlink()
        for file_id in ids:
            (selected_input / f"{file_id}.txt").write_text((input_dir / f"{file_id}.txt").read_text(encoding="utf-8"), encoding="utf-8")
            (selected_gold / f"{file_id}.json").write_text((gold_dir / f"{file_id}.json").read_text(encoding="utf-8"), encoding="utf-8")
        report = evaluator.evaluate_directories(input_dir=selected_input, gold_dir=selected_gold, pred_dir=output_dir, expected_count=len(ids))
    else:
        report = evaluator.evaluate_directories(input_dir=input_dir, gold_dir=gold_dir, pred_dir=output_dir, expected_count=len(ids))
    write_evaluation_report(report, report_dir)
    write_json(report_dir / "runtime.json", {
        "total_seconds": time.perf_counter() - start_time,
        "peak_python_memory_bytes": peak_memory,
        "per_file": per_file,
        "entities_by_type": dict(sorted(counts.items())),
    })
    write_json(report_dir / "resolved_config.json", config.to_serializable())
    print(json.dumps({"files": len(ids), "exact_f1": report.overall_exact.f1, "entities_by_type": dict(counts)}, ensure_ascii=False))
    return 0


def _split_ids(config: dict, split: str) -> list[str]:
    if split == "all":
        values = [*config["development"]["ids"], *config["calibration"]["ids"], *config["lockbox"]["ids"]]
    else:
        values = config[split]["ids"]
    return [str(value) for value in values]


if __name__ == "__main__":
    raise SystemExit(main())