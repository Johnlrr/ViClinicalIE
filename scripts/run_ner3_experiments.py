from __future__ import annotations

import argparse
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config, load_yaml
from src.evaluation import GoldenEvaluator, write_evaluation_report
from src.evaluation.official_like_scorer import score_directories
from src.formatting import PredictionFormatter, write_prediction_json
from src.io_utils import read_json, write_json
from src.ner.candidate_ledger import read_candidate_ledger, write_candidate_ledger
from src.ner.complementarity import EXPERT_SOURCES, analyze_complementarity
from src.ner.experiment_registry import canonical_hash, directory_manifest, file_hash
from src.ner.simple_fusion import resolve_replay_trace
from src.pipeline import ClinicalIEPipeline


CHECKPOINT_MODES = {"A": "v1", "B": "gliner", "C": "naive_union", "D": "simple_fusion"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ledger-backed NER-3 A/B/C/D development experiment.")
    parser.add_argument("--matrix", default="configs/ner3/experiment_matrix.yaml")
    parser.add_argument("--policy", default="configs/ner3/selection_policy.yaml")
    parser.add_argument("--split-config", default="configs/splits_v2.yaml")
    parser.add_argument("--split", default="development")
    parser.add_argument("--checkpoint", action="append", choices=tuple(CHECKPOINT_MODES), default=[])
    parser.add_argument("--input-dir", default="data/golden/input")
    parser.add_argument("--gold-dir", default="data/golden/gold")
    parser.add_argument("--output-root", default="outputs/experiments/ner3")
    parser.add_argument("--ledger-dir", default=None, help="Use an existing ledger directory instead of model extraction.")
    parser.add_argument("--max-files", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    matrix_path, policy_path = Path(args.matrix), Path(args.policy)
    matrix, policy = load_yaml(matrix_path), load_yaml(policy_path)
    checkpoints = validate_checkpoint_plan(matrix)
    _assert_development_only(args.split, policy)
    ids = _split_ids(load_yaml(args.split_config), args.split, args.max_files)
    selected = _select_checkpoints(checkpoints, args.checkpoint)
    root = Path(args.output_root)
    config_path = (matrix_path.parent / str(matrix["base_config"])).resolve()
    config = load_config(config_path, project_root=PROJECT_ROOT)
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else root / "candidate_ledgers"
    input_dir, gold_dir = Path(args.input_dir), Path(args.gold_dir)
    selected_input, selected_gold = _materialize_selected_corpus(ids, input_dir, gold_dir, root / "corpus")

    if args.ledger_dir is None:
        collect_candidate_ledgers(config, ids, input_dir, ledger_dir)
    identity = _ledger_identity(config)
    ledger_manifest = validate_ledgers(
        ids, input_dir, ledger_dir,
        expected_metadata={**identity, "split": "development"},
    )
    ledger_manifest["ledger_dir"] = str(ledger_dir.resolve())
    write_json(root / "candidate_ledger_manifest.json", ledger_manifest)
    complementarity = build_complementarity_report(
        ids, input_dir, gold_dir, ledger_dir,
        near_iou_threshold=float(config.raw.get("ner3", {}).get("complementarity", {}).get("near_iou_threshold", 0.5)),
    )
    write_json(root / "complementarity.json", complementarity)

    completed_now: set[str] = set()
    for spec in selected:
        _assert_prerequisites(spec, root, completed_now)
        run_checkpoint(
            spec=spec, config=config, ids=ids, input_dir=input_dir, gold_dir=gold_dir,
            selected_input=selected_input, selected_gold=selected_gold,
            ledger_dir=ledger_dir, output_root=root, ledger_manifest=ledger_manifest,
            matrix_path=matrix_path, policy_path=policy_path,
        )
        completed_now.add(spec["id"])
    return 0


def validate_checkpoint_plan(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = matrix.get("checkpoints")
    if not isinstance(rows, list):
        raise ValueError("NER-3 matrix checkpoints must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("NER-3 checkpoint must be a mapping")
        item = dict(row)
        checkpoint = str(item.get("id", ""))
        if checkpoint not in CHECKPOINT_MODES or item.get("mode") != CHECKPOINT_MODES[checkpoint]:
            raise ValueError(f"checkpoint {checkpoint or '<missing>'} does not match the approved A/B/C/D plan")
        item["id"] = checkpoint
        item["requires"] = [str(value) for value in item.get("requires", [])]
        normalized.append(item)
    if [row["id"] for row in normalized] != list(CHECKPOINT_MODES):
        raise ValueError("NER-3 checkpoints must be ordered exactly A, B, C, D")
    seen: set[str] = set()
    for row in normalized:
        if not set(row["requires"]) <= seen:
            raise ValueError(f"checkpoint {row['id']} has a forward or unknown dependency")
        seen.add(row["id"])
    return normalized


def collect_candidate_ledgers(config: Any, ids: Sequence[str], input_dir: Path, ledger_dir: Path) -> None:
    """Collect all enabled sources exactly once. This is the only model-bearing step."""
    pipeline = ClinicalIEPipeline(config, ner_only=True)
    metadata = {**_ledger_identity(config), "split": "development"}
    for file_id in ids:
        raw = (input_dir / f"{file_id}.txt").read_text(encoding="utf-8")
        _, candidates = pipeline.collect_ner_candidates(raw)
        write_candidate_ledger(
            ledger_dir / f"{file_id}.json", file_id=file_id, raw_text=raw,
            candidates=candidates, metadata=metadata,
        )


def validate_ledgers(
    ids: Sequence[str], input_dir: Path, ledger_dir: Path, *,
    expected_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    files: dict[str, str] = {}
    source_counts: Counter[str] = Counter()
    evidence_errors = 0
    candidate_count = 0
    for file_id in ids:
        path = ledger_dir / f"{file_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Missing candidate ledger for {file_id}: {path}")
        raw = (input_dir / f"{file_id}.txt").read_text(encoding="utf-8")
        payload, candidates = read_candidate_ledger(path, raw, expected_metadata=expected_metadata)
        if str(payload.get("file_id")) != str(file_id):
            raise ValueError(f"Candidate ledger file_id mismatch for {file_id}")
        files[path.name] = file_hash(path)
        candidate_count += len(candidates)
        source_counts.update(candidate.source for candidate in candidates)
        evidence_errors += int(payload.get("validation", {}).get("evidence_error_count", 0))
    return {
        "schema_version": "ner3-ledger-manifest-v1", "file_count": len(files),
        "candidate_count": candidate_count, "source_candidate_counts": dict(sorted(source_counts.items())),
        "evidence_error_count": evidence_errors, "files": files,
        "manifest_hash": canonical_hash(files),
    }


def build_complementarity_report(
    ids: Sequence[str], input_dir: Path, gold_dir: Path, ledger_dir: Path, *, near_iou_threshold: float,
) -> dict[str, Any]:
    per_file: dict[str, Any] = {}
    for file_id in ids:
        raw = (input_dir / f"{file_id}.txt").read_text(encoding="utf-8")
        _, candidates = read_candidate_ledger(ledger_dir / f"{file_id}.json", raw)
        gliner = [candidate for candidate in candidates if candidate.source == "gliner"]
        experts = [candidate for candidate in candidates if candidate.source in EXPERT_SOURCES]
        gold = read_json(gold_dir / f"{file_id}.json")
        per_file[str(file_id)] = analyze_complementarity(
            gliner, experts, near_iou_threshold=near_iou_threshold, gold_records=gold,
        )
    return {
        "schema_version": "ner3-complementarity-report-v1",
        "near_iou_threshold": near_iou_threshold,
        "aggregate": _sum_complementarity(list(per_file.values())),
        "files": per_file,
    }


def run_checkpoint(
    *, spec: Mapping[str, Any], config: Any, ids: Sequence[str], input_dir: Path,
    gold_dir: Path, selected_input: Path, selected_gold: Path, ledger_dir: Path,
    output_root: Path, ledger_manifest: Mapping[str, Any],
    matrix_path: Path, policy_path: Path,
    downstream_pipeline: Any | None = None,
) -> dict[str, Any]:
    checkpoint, mode = str(spec["id"]), str(spec["mode"])
    run_dir = output_root / checkpoint
    extraction_predictions = run_dir / "predictions" / "extraction_only"
    end_to_end_predictions = run_dir / "predictions" / "end_to_end"
    extraction_evaluation = run_dir / "evaluation" / "extraction_only"
    end_to_end_evaluation = run_dir / "evaluation" / "end_to_end"
    source_trace = run_dir / "source_trace"
    for path in (extraction_predictions, end_to_end_predictions, source_trace):
        _reset_directory(path)
    formatter = PredictionFormatter(config.raw.get("output_format", {}))
    evaluator = GoldenEvaluator(config.raw.get("evaluation", {}), config.raw.get("prediction_validation", {}))
    downstream = downstream_pipeline or ClinicalIEPipeline(config, ner_only=False)
    duplicate_count = 0
    anchor_count = 0
    unresolved_count = 0
    gliner_unconfirmed_total = 0
    gliner_unconfirmed_survived = 0
    extraction_entities = 0
    end_to_end_entities = 0
    per_file_runtime: dict[str, Any] = {}
    started = time.perf_counter()
    for file_id in ids:
        file_started = time.perf_counter()
        raw = (input_dir / f"{file_id}.txt").read_text(encoding="utf-8")
        _, candidates = read_candidate_ledger(ledger_dir / f"{file_id}.json", raw)
        trace = resolve_replay_trace(
            candidates, raw, mode=mode,
            resolver_config=config.raw.get("type_resolution", {}),
            fusion_config=config.raw.get("ner3", {}).get("fusion", {}),
        )
        records = formatter.format_entities(trace.entities)
        write_prediction_json(records, extraction_predictions / f"{file_id}.json", config.raw.get("output_format", {}))
        downstream_result = downstream.process_resolved_end_to_end(raw, trace.entities, file_id=file_id)
        write_prediction_json(
            downstream_result.records, end_to_end_predictions / f"{file_id}.json", config.raw.get("output_format", {}),
        )
        extraction_entities += len(records)
        end_to_end_entities += len(downstream_result.records)
        write_json(source_trace / f"{file_id}.json", {
            "file_id": file_id, "mode": mode,
            "anchor_events": trace.anchor_events,
            "resolver_conflicts": [_dataclass_payload(value) for value in trace.conflicts],
            "resolver_overlaps": [_dataclass_payload(value) for value in trace.overlaps],
            "entities": [{
                "text": entity.text, "position": entity.position, "type": str(entity.type),
                "confidence": entity.confidence, "provenance": entity.provenance,
            } for entity in trace.entities],
        })
        per_file_runtime[file_id] = {"seconds": time.perf_counter() - file_started, "candidate_count": len(candidates)}
        # The completion gate concerns duplicate exact entities in final NER
        # output. Resolver input deduplication is diagnostic and is not itself
        # an output-schema failure.
        duplicate_count += _duplicate_exact_count(records)
        anchor_count += len(trace.anchor_events)
        unresolved_count += len(trace.unresolved)
        if mode == "simple_fusion":
            total, survived = _gliner_unconfirmed_survival(candidates, trace.entities)
            gliner_unconfirmed_total += total
            gliner_unconfirmed_survived += survived
    extraction_report = evaluator.evaluate_directories(
        input_dir=selected_input, gold_dir=selected_gold, pred_dir=extraction_predictions, expected_count=len(ids),
    )
    write_evaluation_report(extraction_report, extraction_evaluation)
    end_to_end_report = evaluator.evaluate_directories(
        input_dir=selected_input, gold_dir=selected_gold, pred_dir=end_to_end_predictions, expected_count=len(ids),
    )
    write_evaluation_report(end_to_end_report, end_to_end_evaluation)
    official = score_directories(end_to_end_predictions, selected_gold, ids=ids).to_dict()
    write_json(run_dir / "official_like_score.json", official)
    density = {
        "files": len(ids), "gold_entities": extraction_report.gold_entities,
        "extraction_entities": extraction_entities, "end_to_end_entities": end_to_end_entities,
        "extraction_mean_entities_per_note": extraction_entities / len(ids) if ids else 0.0,
        "pred_to_gold_ratio": extraction_entities / extraction_report.gold_entities if extraction_report.gold_entities else None,
        "density_ratio": _density_ratio_to_a(checkpoint, output_root, extraction_entities),
    }
    runtime = {"total_seconds": time.perf_counter() - started, "files": per_file_runtime}
    write_json(run_dir / "density.json", density)
    write_json(run_dir / "runtime.json", runtime)
    write_json(run_dir / "resolved_config.json", config.to_serializable() if hasattr(config, "to_serializable") else config.raw)
    metrics = extraction_report.to_dict()
    manifest = {
        "schema_version": "ner3-run-manifest-v1", "checkpoint": checkpoint,
        "name": spec.get("name"), "mode": mode, "requires": list(spec.get("requires", [])),
        "diagnostic_only": bool(spec.get("diagnostic_only", False)), "split": "development",
        "sample_ids": list(ids), "ledger_manifest_hash": ledger_manifest["manifest_hash"],
        "ledger_evidence_error_count": ledger_manifest["evidence_error_count"],
        "matrix_hash": file_hash(matrix_path), "policy_hash": file_hash(policy_path),
        "config_path": str(config.config_path), "resolved_config_hash": canonical_hash(config.raw),
        "prediction_hashes": {
            "extraction_only": directory_manifest(extraction_predictions, "*.json"),
            "end_to_end": directory_manifest(end_to_end_predictions, "*.json"),
        },
        "metrics": metrics, "end_to_end_metrics": end_to_end_report.to_dict(),
        "official_like_final_score": official["final_score"], "density": density, "runtime": runtime,
        "validation_error_count": 0,
        "duplicate_exact_span_count": duplicate_count,
        "resolver_unresolved_count": unresolved_count, "structured_anchor_event_count": anchor_count,
        "gliner_unconfirmed": {
            "total": gliner_unconfirmed_total, "survived_exact": gliner_unconfirmed_survived,
        },
    }
    write_json(run_dir / "prediction_diff.json", _prediction_diff(checkpoint, output_root, extraction_predictions))
    write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def _sum_complementarity(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    categories: Counter[str] = Counter()
    by_type: dict[str, Counter[str]] = {}
    by_source: dict[str, Any] = {}
    by_source_type: dict[str, dict[str, Counter[str]]] = {}
    anchors = 0
    for report in reports:
        categories.update(report.get("category_counts", {}))
        anchors += len(report.get("structured_anchor_opportunities", []))
        for entity_type, values in report.get("by_type", {}).items():
            by_type.setdefault(str(entity_type), Counter()).update(values)
        for source, values in report.get("by_source", {}).items():
            target = by_source.setdefault(source, {"expert_candidate_count": 0, "categories": Counter(), "gold_utility": Counter()})
            target["expert_candidate_count"] += int(values.get("expert_candidate_count", 0))
            target["categories"].update(values.get("categories", {}))
            utility = values.get("gold_utility", {})
            target["gold_utility"].update({key: value for key, value in utility.items() if isinstance(value, int)})
        for match in report.get("matches", []):
            if not isinstance(match, Mapping):
                continue
            source = str(match.get("second_source") or match.get("first_source") or "unknown")
            entity_type = str(match.get("second_type") or match.get("first_type") or "UNKNOWN")
            category = str(match.get("category", "unknown"))
            by_source_type.setdefault(source, {}).setdefault(entity_type, Counter())[category] += 1
    return {
        "category_counts": dict(sorted(categories.items())),
        "by_type": {key: dict(sorted(value.items())) for key, value in sorted(by_type.items())},
        "by_source": {
            key: {"expert_candidate_count": value["expert_candidate_count"],
                  "categories": dict(sorted(value["categories"].items())),
                  "gold_utility": dict(sorted(value["gold_utility"].items()))}
            for key, value in sorted(by_source.items())
        },
        "by_source_type": {
            source: {entity_type: dict(sorted(counts.items())) for entity_type, counts in sorted(types.items())}
            for source, types in sorted(by_source_type.items())
        },
        "structured_anchor_opportunity_count": anchors,
    }


def _gliner_unconfirmed_survival(candidates: Sequence[Any], entities: Sequence[Any]) -> tuple[int, int]:
    experts = [item for item in candidates if item.source in EXPERT_SOURCES]
    gliner_only = {
        (item.start, item.end, str(item.raw_type))
        for item in candidates
        if item.source == "gliner" and not any(
            max(item.start, expert.start) < min(item.end, expert.end) for expert in experts
        )
    }
    output = {(item.start, item.end, str(item.type)) for item in entities}
    return len(gliner_only), len(gliner_only & output)


def _duplicate_exact_count(records: Sequence[Mapping[str, Any]]) -> int:
    keys = [(tuple(row.get("position", [])), str(row.get("type", ""))) for row in records]
    return len(keys) - len(set(keys))


def _assert_development_only(split: str, policy: Mapping[str, Any]) -> None:
    allowed = str(policy.get("allowed_split", "development"))
    if split != allowed:
        raise PermissionError(f"NER-3 source/fusion selection is development-only; {split!r} is forbidden")


def _split_ids(splits: Mapping[str, Any], split: str, max_files: int | None) -> list[str]:
    if max_files is not None and max_files < 0:
        raise ValueError("--max-files must be non-negative")
    values = [str(value) for value in splits[split]["ids"]]
    return values if max_files is None else values[:max_files]


def _select_checkpoints(checkpoints: Sequence[dict[str, Any]], requested: Sequence[str]) -> list[dict[str, Any]]:
    if not requested:
        return list(checkpoints)
    wanted = set(requested)
    return [row for row in checkpoints if row["id"] in wanted]


def _assert_prerequisites(spec: Mapping[str, Any], root: Path, completed_now: set[str]) -> None:
    missing = [value for value in spec.get("requires", []) if value not in completed_now and not (root / value / "run_manifest.json").is_file()]
    if missing:
        raise PermissionError(f"checkpoint {spec['id']} requires completed checkpoints: {', '.join(missing)}")


def _reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _materialize_selected_corpus(
    ids: Sequence[str], input_dir: Path, gold_dir: Path, target: Path,
) -> tuple[Path, Path]:
    selected_input, selected_gold = target / "input", target / "gold"
    _reset_directory(selected_input)
    _reset_directory(selected_gold)
    for file_id in ids:
        shutil.copy2(input_dir / f"{file_id}.txt", selected_input / f"{file_id}.txt")
        shutil.copy2(gold_dir / f"{file_id}.json", selected_gold / f"{file_id}.json")
    return selected_input, selected_gold


def _ledger_identity(config: Any) -> dict[str, str]:
    gliner = config.raw.get("extractors", {}).get("gliner", {})
    model_identity = {
        "model_name_or_path": gliner.get("model_name_or_path"),
        "model_revision": gliner.get("model_revision"),
        "tokenizer_name_or_path": gliner.get("windowing", {}).get("tokenizer_name_or_path"),
        "tokenizer_revision": gliner.get("windowing", {}).get("tokenizer_revision"),
    }
    return {
        "config_hash": canonical_hash(config.raw),
        "model_hash": canonical_hash(model_identity),
        "selected_config_hash": file_hash(PROJECT_ROOT / "configs/ner2/selected_zero_shot.yaml"),
    }


def _dataclass_payload(value: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass
    return asdict(value) if is_dataclass(value) else dict(value) if isinstance(value, Mapping) else {"value": str(value)}


def _prediction_diff(checkpoint: str, output_root: Path, current: Path) -> dict[str, Any]:
    parent = {"B": "A", "C": "B", "D": "C"}.get(checkpoint)
    current_hashes = directory_manifest(current, "*.json")
    parent_path = output_root / str(parent) / "predictions" / "extraction_only" if parent else None
    parent_hashes = directory_manifest(parent_path, "*.json") if parent_path and parent_path.is_dir() else {}
    names = sorted(set(current_hashes) | set(parent_hashes))
    return {
        "parent_checkpoint": parent, "files_compared": len(names),
        "changed_files": [name for name in names if current_hashes.get(name) != parent_hashes.get(name)],
        "added_files": [name for name in names if name not in parent_hashes],
        "removed_files": [name for name in names if name not in current_hashes],
    }


def _density_ratio_to_a(checkpoint: str, output_root: Path, extraction_entities: int) -> float | None:
    if checkpoint == "A":
        return 1.0
    baseline_path = output_root / "A" / "density.json"
    if not baseline_path.is_file():
        return None
    baseline = int(read_json(baseline_path).get("extraction_entities", 0))
    return extraction_entities / baseline if baseline else None


if __name__ == "__main__":
    raise SystemExit(main())