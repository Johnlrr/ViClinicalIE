from __future__ import annotations

import argparse
import copy
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

from src.assertion import AssertionDetector, load_assertion_rules
from src.config import load_config
from src.data_types import FinalEntity, VALID_ASSERTIONS
from src.extractors import ExtractionContext, build_default_extractors
from src.io_utils import read_text
from src.linking.icd10_linker import ICD10Linker
from src.linking.rxnorm_linker import RxNormLinker
from src.postprocess import Postprocessor, remaining_overlap_count
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import detect_sections, load_section_patterns
from src.type_resolution import TypeResolver

ASSERTABLE_TYPES = {"TRIỆU_CHỨNG", "CHẨN_ĐOÁN", "THUỐC"}
LINKED_TYPES = {"CHẨN_ĐOÁN", "THUỐC"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 10 postprocess smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=2, help="Maximum files to check.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based offset into the sampled file list for batched smoke runs.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Maximum debug samples to print per category.")
    parser.add_argument(
        "--enable-sparse-retrieval",
        action="store_true",
        help="Use configured TF-IDF/BM25 linker retrieval. By default Phase 10 smoke uses exact-linking only for speed.",
    )
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    raw_config = copy.deepcopy(config.raw)
    if not args.enable_sparse_retrieval:
        _disable_sparse_linker_retrieval(raw_config)
    section_cfg = config.raw.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    extractors = build_default_extractors(config)
    resolver = TypeResolver(raw_config.get("type_resolution", {}))
    assertion_cfg = dict(raw_config.get("assertion_detection", {}))
    rules = _load_assertion_rules(config.config_path, assertion_cfg)
    detector = AssertionDetector(assertion_cfg, rules=rules)
    icd_linker = ICD10Linker(config.path("processed_dir"), raw_config.get("icd10_linking", {}))
    rx_linker = RxNormLinker(config.path("processed_dir"), raw_config.get("rxnorm_linking", {}))
    postprocessor = Postprocessor(raw_config.get("postprocess", {}))

    files = _sample_files(config, args.max_files, args.start_index)
    if not files:
        raise FileNotFoundError("No input files found for Phase 10 smoke check")

    entity_counts: Counter[str] = Counter()
    offset_errors: list[str] = []
    wrong_type_candidate_errors: list[str] = []
    invalid_assertion_errors: list[str] = []
    duplicate_exact_errors: list[str] = []
    sample_dropped: list[str] = []
    sample_trimmed: list[str] = []
    sample_overlap_resolutions: list[str] = []

    total_chunks = 0
    total_span_candidates = 0
    total_before_postprocess = 0
    total_after_postprocess = 0
    total_exact_duplicates_removed = 0
    total_same_type_overlaps_resolved = 0
    total_different_type_overlaps_resolved = 0
    total_entities_trimmed = 0
    total_entities_dropped = 0
    total_candidate_cleanups = 0
    total_assertion_cleanups = 0
    total_remaining_overlaps = 0

    for path in files:
        raw_text = read_text(path, encoding=str(raw_config.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, raw_config)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        total_chunks += len(chunks)
        context = ExtractionContext(raw_text=raw_text, views=output.views, chunks=chunks, config=raw_config)

        span_candidates = []
        for extractor in extractors:
            span_candidates.extend(extractor.extract(context))
        entities = resolver.resolve(span_candidates, raw_text)
        asserted = detector.apply(entities, raw_text)
        icd_linked = icd_linker.link_entities(asserted, raw_text=raw_text)
        linked = rx_linker.link_entities(icd_linked, raw_text=raw_text)
        result = postprocessor.process(linked, raw_text=raw_text)
        postprocessed = result.entities
        report = result.report

        total_span_candidates += len(span_candidates)
        total_before_postprocess += len(linked)
        total_after_postprocess += len(postprocessed)
        total_exact_duplicates_removed += report.exact_duplicates_removed
        total_same_type_overlaps_resolved += report.same_type_overlaps_resolved
        total_different_type_overlaps_resolved += report.different_type_overlaps_resolved
        total_entities_trimmed += report.entities_trimmed
        total_entities_dropped += report.entities_dropped
        total_candidate_cleanups += report.candidate_cleanups
        total_assertion_cleanups += report.assertion_cleanups
        offset_errors.extend(f"{path.name}:{item}" for item in report.offset_errors)
        total_remaining_overlaps += remaining_overlap_count(postprocessed)
        entity_counts.update(str(entity.type) for entity in postprocessed)

        duplicate_exact_errors.extend(_duplicate_exact_errors(path.name, postprocessed))
        wrong_type_candidate_errors.extend(_wrong_type_candidate_errors(path.name, postprocessed))
        invalid_assertion_errors.extend(_invalid_assertion_errors(path.name, postprocessed))
        _collect_decision_samples(path.name, report.decisions, sample_dropped, sample_trimmed, sample_overlap_resolutions, args.sample_limit)

    print("Phase 10 smoke checks completed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_checked: {total_chunks}")
    print(f"span_candidates: {total_span_candidates}")
    print(f"entities_before_postprocess: {total_before_postprocess}")
    print(f"entities_after_postprocess: {total_after_postprocess}")
    print(f"exact_duplicates_removed: {total_exact_duplicates_removed}")
    print(f"same_type_overlaps_resolved: {total_same_type_overlaps_resolved}")
    print(f"different_type_overlaps_resolved: {total_different_type_overlaps_resolved}")
    print(f"entities_trimmed: {total_entities_trimmed}")
    print(f"entities_dropped: {total_entities_dropped}")
    print(f"candidate_cleanups: {total_candidate_cleanups}")
    print(f"assertion_cleanups: {total_assertion_cleanups}")
    print(f"entities_by_type: {dict(sorted(entity_counts.items()))}")
    print(f"offset_error_count: {len(offset_errors)}")
    print(f"wrong_type_candidate_error_count: {len(wrong_type_candidate_errors)}")
    print(f"invalid_assertion_count: {len(invalid_assertion_errors)}")
    print(f"duplicate_exact_error_count: {len(duplicate_exact_errors)}")
    print(f"remaining_overlap_count: {total_remaining_overlaps}")

    for label, errors in (
        ("OFFSET_ERROR", offset_errors),
        ("WRONG_TYPE_CANDIDATE_ERROR", wrong_type_candidate_errors),
        ("INVALID_ASSERTION_ERROR", invalid_assertion_errors),
        ("DUPLICATE_EXACT_ERROR", duplicate_exact_errors),
    ):
        for item in errors[:20]:
            print(f"{label}: {item}")

    _print_samples("sample_dropped_entities", sample_dropped)
    _print_samples("sample_trimmed_entities", sample_trimmed)
    _print_samples("sample_overlap_resolutions", sample_overlap_resolutions)

    if offset_errors or wrong_type_candidate_errors or invalid_assertion_errors or duplicate_exact_errors:
        return 1
    return 0


def _resolve_patterns_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _load_assertion_rules(config_path: Path, assertion_cfg: dict[str, Any]) -> dict[str, list[str]]:
    rules_value = assertion_cfg.get("rules_config")
    if not rules_value:
        return {}
    rules_path = _resolve_patterns_path(config_path, str(rules_value))
    return load_assertion_rules(rules_path)


def _disable_sparse_linker_retrieval(raw_config: dict[str, Any]) -> None:
    for section_name in ("icd10_linking", "rxnorm_linking"):
        section = raw_config.get(section_name, {})
        if not isinstance(section, dict):
            continue
        retrieval = section.setdefault("retrieval", {})
        if not isinstance(retrieval, dict):
            retrieval = {}
            section["retrieval"] = retrieval
        retrieval["top_k_tfidf"] = 0
        retrieval["top_k_bm25"] = 0


def _sample_files(config, max_files: int, start_index: int = 0) -> list[Path]:
    candidates: list[Path] = []
    for key in ("golden_input_dir", "raw_input_dir"):
        if key in config.paths and config.path(key).is_dir():
            candidates.extend(sorted(config.path(key).glob("*.txt")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if len(seen) <= start_index:
            continue
        unique.append(path)
        if len(unique) >= max_files:
            break
    return unique


def _duplicate_exact_errors(file_name: str, entities: list[FinalEntity]) -> list[str]:
    counts: Counter[tuple[int, int, str]] = Counter((entity.start, entity.end, str(entity.type)) for entity in entities)
    return [f"{file_name}:{start}-{end}:{entity_type}:count={count}" for (start, end, entity_type), count in counts.items() if count > 1]


def _wrong_type_candidate_errors(file_name: str, entities: list[FinalEntity]) -> list[str]:
    return [
        f"{file_name}:{entity.position}:{entity.type}:{entity.text!r}:{entity.candidates}"
        for entity in entities
        if str(entity.type) not in LINKED_TYPES and entity.candidates
    ]


def _invalid_assertion_errors(file_name: str, entities: list[FinalEntity]) -> list[str]:
    errors: list[str] = []
    for entity in entities:
        invalid_values = [assertion for assertion in entity.assertions if assertion not in VALID_ASSERTIONS]
        if invalid_values:
            errors.append(f"{file_name}:{entity.position}:{entity.type}:{entity.text!r}:invalid={invalid_values}")
        if str(entity.type) not in ASSERTABLE_TYPES and entity.assertions:
            errors.append(f"{file_name}:{entity.position}:{entity.type}:{entity.text!r}:non_assertable={entity.assertions}")
    return errors


def _collect_decision_samples(
    file_name: str,
    decisions,
    sample_dropped: list[str],
    sample_trimmed: list[str],
    sample_overlap_resolutions: list[str],
    sample_limit: int,
) -> None:
    for decision in decisions:
        if decision.action == "drop_entity" and len(sample_dropped) < sample_limit:
            sample_dropped.append(f"{file_name} | {decision.reason} | removed={decision.removed[:1]}")
        elif decision.action == "trim_entity" and len(sample_trimmed) < sample_limit:
            sample_trimmed.append(f"{file_name} | before={decision.before} | after={decision.after}")
        elif "overlap" in decision.action and len(sample_overlap_resolutions) < sample_limit:
            sample_overlap_resolutions.append(f"{file_name} | {decision.reason} | kept={decision.kept} | removed={decision.removed[:1]}")


def _print_samples(label: str, samples: list[str]) -> None:
    print(f"{label}:")
    for sample in samples:
        print(f"  {sample}")


if __name__ == "__main__":
    raise SystemExit(main())