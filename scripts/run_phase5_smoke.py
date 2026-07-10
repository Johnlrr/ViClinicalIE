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
from src.type_resolution import TypeResolver


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 5 type resolution smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=4, help="Maximum files to check.")
    parser.add_argument("--sample-limit", type=int, default=30, help="Maximum sample entities/conflicts to print.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    section_cfg = config.raw.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    extractors = build_default_extractors(config)
    resolver = TypeResolver(config.raw.get("type_resolution", {}))
    files = _sample_files(config, args.max_files)
    if not files:
        raise FileNotFoundError("No input files found for Phase 5 smoke check")

    entity_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    offset_errors: list[str] = []
    sample_entities: list[str] = []
    sample_conflicts: list[str] = []
    sample_overlaps: list[str] = []
    total_candidates = 0
    total_entities = 0
    total_conflicts = 0
    total_duplicates = 0
    total_overlaps = 0
    total_unresolved = 0
    total_chunks = 0

    for path in files:
        raw_text = read_text(path, encoding=str(config.raw.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, config.raw)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        total_chunks += len(chunks)
        context = ExtractionContext(raw_text=raw_text, views=output.views, chunks=chunks, config=config.raw)
        candidates = []
        for extractor in extractors:
            extracted = extractor.extract(context)
            candidates.extend(extracted)
            source_counts.update(candidate.source for candidate in extracted)
        entities = resolver.resolve(candidates, raw_text)
        total_candidates += len(candidates)
        total_entities += len(entities)
        total_conflicts += len(resolver.conflicts)
        total_duplicates += resolver.duplicate_exact_span_count
        total_overlaps += len(resolver.overlaps)
        total_unresolved += len(resolver.unresolved)
        entity_counts.update(str(entity.type) for entity in entities)
        for entity in entities:
            if raw_text[entity.start : entity.end] != entity.text:
                offset_errors.append(f"{path.name}:{entity.start}-{entity.end}:{entity.type}:{entity.text!r}")
            if len(sample_entities) < args.sample_limit:
                sample_entities.append(f"{path.name} | {entity.type} | {entity.position} | {entity.text} | {entity.provenance.get('chosen_source')}")
        for conflict in resolver.conflicts:
            if len(sample_conflicts) < args.sample_limit:
                sample_conflicts.append(
                    f"{path.name} | {conflict.text} | chosen={conflict.chosen_type} | rejected={conflict.rejected_types} | sources={conflict.sources}"
                )
        for overlap in resolver.overlaps:
            if len(sample_overlaps) < args.sample_limit:
                sample_overlaps.append(
                    f"{path.name} | {overlap.text} [{overlap.start},{overlap.end}] <> {overlap.other_text} "
                    f"[{overlap.other_start},{overlap.other_end}] | types={overlap.types} | overlap={overlap.overlap_text!r}"
                )

    print("Phase 5 smoke checks completed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_checked: {total_chunks}")
    print(f"span_candidates: {total_candidates}")
    print(f"final_entities: {total_entities}")
    print(f"candidate_count_by_source: {dict(sorted(source_counts.items()))}")
    print(f"entities_by_type: {dict(sorted(entity_counts.items()))}")
    print(f"conflict_count: {total_conflicts}")
    print(f"duplicate_exact_span_count: {total_duplicates}")
    print(f"overlap_count: {total_overlaps}")
    print(f"unresolved_count: {total_unresolved}")
    print(f"offset_error_count: {len(offset_errors)}")
    if offset_errors:
        for item in offset_errors[:20]:
            print(f"OFFSET_ERROR: {item}")
        return 1
    print("sample_entities:")
    for sample in sample_entities:
        print(f"  {sample}")
    if sample_conflicts:
        print("sample_conflicts:")
        for sample in sample_conflicts:
            print(f"  {sample}")
    if sample_overlaps:
        print("sample_overlaps:")
        for sample in sample_overlaps:
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
