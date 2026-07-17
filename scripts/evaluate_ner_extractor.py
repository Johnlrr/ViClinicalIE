from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.extractors.base import ExtractionContext
from src.extractors.ner_extractor import NERExtractor
from src.io_utils import write_json
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import detect_sections, load_section_patterns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-evaluate the Phase 14 NER extractor scaffold without training.")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--input-dir", default="data/golden/input")
    parser.add_argument("--report-dir", default="outputs/reports/phase14_ner_extractor_smoke")
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--force-enable", action="store_true", help="Enable NER extractor even if config extractors.ner.enabled is false; missing model still returns no spans.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    raw_config = dict(config.raw)
    ner_cfg = dict(raw_config.get("extractors", {}).get("ner", {}))
    if args.force_enable:
        ner_cfg["enabled"] = True
    extractor = NERExtractor(config=ner_cfg)

    section_cfg = dict(raw_config.get("section_detection", {}))
    patterns_path = _resolve(config.config_path.parent, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)

    rows = []
    type_counter: Counter[str] = Counter()
    files = sorted(Path(args.input_dir).glob("*.txt"), key=lambda item: _natural_key(item.stem))[: args.max_files]
    offset_errors = []
    for path in files:
        raw_text = path.read_text(encoding=str(raw_config.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, raw_config)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        context = ExtractionContext(raw_text=raw_text, views=output.views, chunks=chunks, config=raw_config)
        candidates = extractor.extract(context)
        for candidate in candidates:
            if raw_text[candidate.start : candidate.end] != candidate.text:
                offset_errors.append({"file_id": path.stem, "text": candidate.text, "position": [candidate.start, candidate.end]})
            type_counter[str(candidate.raw_type)] += 1
        rows.append({"file_id": path.stem, "candidate_count": len(candidates)})

    report = {
        "files_checked": len(files),
        "extractor_enabled": extractor.enabled,
        "model_available": extractor.model_runner.available,
        "model_error": extractor.model_runner.error,
        "candidate_count": sum(row["candidate_count"] for row in rows),
        "candidate_count_by_type": dict(sorted(type_counter.items())),
        "offset_error_count": len(offset_errors),
        "offset_errors": offset_errors,
        "files": rows,
    }
    target = Path(args.report_dir)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "summary.json", report)
    print("Phase 14 NER extractor smoke completed.")
    for key in ("files_checked", "extractor_enabled", "model_available", "candidate_count", "offset_error_count"):
        print(f"{key}: {report[key]}")
    if report["model_error"]:
        print(f"model_error: {report['model_error']}")


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _natural_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


if __name__ == "__main__":
    main()
