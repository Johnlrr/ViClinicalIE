from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.assertion import AssertionDetector, load_assertion_rules
from src.config import load_config
from src.extractors import ExtractionContext, build_default_extractors
from src.io_utils import read_text
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import detect_sections, load_section_patterns
from src.type_resolution import TypeResolver


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 6 assertion detection smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=4, help="Maximum files to check.")
    parser.add_argument("--sample-limit", type=int, default=30, help="Maximum sample asserted entities to print.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    section_cfg = config.raw.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    extractors = build_default_extractors(config)
    resolver = TypeResolver(config.raw.get("type_resolution", {}))
    assertion_cfg = dict(config.raw.get("assertion_detection", {}))
    rules = _load_assertion_rules(config.config_path, assertion_cfg)
    detector = AssertionDetector(assertion_cfg, rules=rules)
    files = _sample_files(config, args.max_files)
    if not files:
        raise FileNotFoundError("No input files found for Phase 6 smoke check")

    entity_counts: Counter[str] = Counter()
    assertion_counts: Counter[str] = Counter()
    asserted_by_type: Counter[str] = Counter()
    offset_errors: list[str] = []
    sample_asserted: list[str] = []
    total_candidates = 0
    total_entities = 0
    total_assertable = 0
    total_chunks = 0

    for path in files:
        raw_text = read_text(path, encoding=str(config.raw.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, config.raw)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        total_chunks += len(chunks)
        context = ExtractionContext(raw_text=raw_text, views=output.views, chunks=chunks, config=config.raw)
        candidates = []
        for extractor in extractors:
            candidates.extend(extractor.extract(context))
        entities = resolver.resolve(candidates, raw_text)
        asserted = detector.apply(entities, raw_text)
        total_candidates += len(candidates)
        total_entities += len(asserted)

        for entity in asserted:
            entity_counts.update([str(entity.type)])
            if str(entity.type) in detector.assertable_types:
                total_assertable += 1
            if raw_text[entity.start : entity.end] != entity.text:
                offset_errors.append(f"{path.name}:{entity.start}-{entity.end}:{entity.type}:{entity.text!r}")
            for assertion in entity.assertions:
                assertion_counts.update([assertion])
                asserted_by_type.update([str(entity.type)])
            if entity.assertions and len(sample_asserted) < args.sample_limit:
                sample_asserted.append(
                    f"{path.name} | {entity.type} | {entity.assertions} | {entity.position} | {entity.text} | "
                    f"evidence={entity.provenance.get('assertion', {}).get('evidence', [])[:2]}"
                )

    print("Phase 6 smoke checks completed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_checked: {total_chunks}")
    print(f"span_candidates: {total_candidates}")
    print(f"final_entities: {total_entities}")
    print(f"assertable_entities: {total_assertable}")
    print(f"entities_by_type: {dict(sorted(entity_counts.items()))}")
    print(f"assertion_counts: {dict(sorted(assertion_counts.items()))}")
    print(f"asserted_entities_by_type: {dict(sorted(asserted_by_type.items()))}")
    print(f"offset_error_count: {len(offset_errors)}")
    if offset_errors:
        for item in offset_errors[:20]:
            print(f"OFFSET_ERROR: {item}")
        return 1
    print("sample_asserted_entities:")
    for sample in sample_asserted:
        print(f"  {sample}")
    return 0


def _resolve_patterns_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _load_assertion_rules(config_path: Path, assertion_cfg: dict) -> dict[str, list[str]]:
    rules_value = assertion_cfg.get("rules_config")
    if not rules_value:
        return {}
    rules_path = _resolve_patterns_path(config_path, str(rules_value))
    return load_assertion_rules(rules_path)


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