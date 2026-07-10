from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.extractors import ExtractionContext, build_default_extractors
from src.io_utils import read_text
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import detect_sections, load_section_patterns


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 4 span extraction smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=4, help="Maximum files to check.")
    parser.add_argument("--sample-limit", type=int, default=30, help="Maximum sample candidates to print.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    section_cfg = config.raw.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    extractors = build_default_extractors(config)
    files = _sample_files(config, args.max_files)
    if not files:
        raise FileNotFoundError("No input files found for Phase 4 smoke check")

    source_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    offset_errors: list[str] = []
    samples: list[str] = []
    total_chunks = 0
    total_candidates = 0

    for path in files:
        raw_text = read_text(path, encoding=str(config.raw.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, config.raw)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        total_chunks += len(chunks)
        context = ExtractionContext(raw_text=raw_text, views=output.views, chunks=chunks, config=config.raw)
        for extractor in extractors:
            candidates = extractor.extract(context)
            total_candidates += len(candidates)
            for cand in candidates:
                source_counts[cand.source] += 1
                type_counts[str(cand.raw_type)] += 1
                if raw_text[cand.start : cand.end] != cand.text:
                    offset_errors.append(f"{path.name}:{cand.start}-{cand.end}:{cand.source}:{cand.text!r}")
                if len(samples) < args.sample_limit:
                    samples.append(f"{path.name} | {cand.source} | {cand.raw_type} | {cand.position if hasattr(cand, 'position') else [cand.start, cand.end]} | {cand.text}")

    print("Phase 4 smoke checks completed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_checked: {total_chunks}")
    print(f"total_candidates: {total_candidates}")
    print(f"candidate_count_by_source: {dict(sorted(source_counts.items()))}")
    print(f"candidate_count_by_raw_type: {dict(sorted(type_counts.items()))}")
    print(f"offset_error_count: {len(offset_errors)}")
    if offset_errors:
        for item in offset_errors[:20]:
            print(f"OFFSET_ERROR: {item}")
        return 1
    print("sample_candidates:")
    for sample in samples:
        print(f"  {sample}")
    return 0


def _resolve_patterns_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _sample_files(config, max_files: int) -> list[Path]:
    candidates: list[Path] = []
    for key in ("golden_input_dir", "raw_input_dir"):
        if key in config.paths and config.path(key).is_dir():
            candidates.extend(sorted(config.path(key).glob("*.txt"))[:max_files])
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
        if len(unique) >= max_files:
            break
    return unique


if __name__ == "__main__":
    raise SystemExit(main())
