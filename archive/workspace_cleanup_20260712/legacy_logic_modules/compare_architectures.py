"""Build, score, and compare old V0-linked outputs with new architecture outputs.

The comparison has two modes:
  * with --gold-dir: score old and new outputs against the same silver/gold set
  * without usable gold: compare new output JSON directly against old output JSON

By default this script builds both output directories. Use --skip-build-old or
--skip-build-new when the artifacts already exist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.score_silver import ScoreReport, discover_file_ids, score_directories, write_json_report, write_markdown_report


def configure_stdout() -> None:
    """Make Vietnamese output safe on Windows consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def numeric_sort_key(value: str | Path) -> Tuple[int, str]:
    """Sort numeric file ids naturally."""
    stem = Path(value).stem if isinstance(value, Path) else str(value)
    return (int(stem), stem) if stem.isdigit() else (1 << 30, stem)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare old V0-linked and new-architecture ViClinicalIE outputs.")
    parser.add_argument("--input-dir", type=Path, default=ROOT / "input", help="Input *.txt directory.")
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "silver_test" / "output", help="Optional silver/gold output directory.")
    parser.add_argument("--old-outputs-dir", type=Path, default=ROOT / "outputs" / "v0_linked", help="Old architecture artifact directory containing output/.")
    parser.add_argument("--new-outputs-dir", type=Path, default=ROOT / "outputs" / "new_arch", help="New architecture artifact directory containing output/.")
    parser.add_argument("--analysis-dir", type=Path, default=ROOT / "analysis", help="Analysis artifact directory.")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "reports", help="Report artifact directory.")
    parser.add_argument("--resource-dir", type=Path, default=ROOT / "data_resources", help="Dictionary/linker resource directory.")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N file ids by numeric order.")
    parser.add_argument("--only", default=None, help="Comma-separated file ids to process/compare, e.g. 1,2,3.")
    parser.add_argument("--skip-build-old", action="store_true", help="Do not rebuild old V0-linked outputs.")
    parser.add_argument("--skip-build-new", action="store_true", help="Do not rebuild new-architecture outputs.")
    parser.add_argument("--skip-mapping-gate", action="store_true", help="Pass through to old builder to avoid failing low mapping coverage.")
    parser.add_argument("--ner-model", default=None, help="Hugging Face model id or local checkpoint for optional NER.")
    parser.add_argument("--ner-device", default=None, help="NER device override, e.g. cpu, cuda, cuda:0.")
    parser.add_argument("--ner-max-length", type=int, default=512, help="NER tokenizer max_length for new builder.")
    parser.add_argument("--ner-threshold", action="append", default=[], help="Pass through ENTITY_TYPE=FLOAT NER threshold; repeatable.")
    parser.add_argument("--skip-ner", action="store_true", help="Run new architecture without NER.")
    parser.add_argument("--report-md", type=Path, default=ROOT / "reports" / "architecture_comparison.md", help="Comparison Markdown report path.")
    parser.add_argument("--report-json", type=Path, default=ROOT / "reports" / "architecture_comparison.json", help="Comparison JSON report path.")
    return parser.parse_args()


def append_selection_args(command: List[str], *, only: Optional[str], limit: Optional[int]) -> None:
    """Append shared --only/--limit args to a subprocess command."""
    if only:
        command.extend(["--only", only])
    if limit is not None:
        command.extend(["--limit", str(limit)])


def run_command(command: Sequence[str]) -> None:
    """Run a Python subprocess and stream output."""
    print("$ " + " ".join(str(part) for part in command))
    subprocess.check_call(list(command), cwd=ROOT)


def build_old(args: argparse.Namespace) -> None:
    """Build old V0-linked outputs."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_v0_linked_outputs.py"),
        "--input-dir",
        str(args.input_dir),
        "--outputs-dir",
        str(args.old_outputs_dir),
        "--analysis-dir",
        str(args.analysis_dir),
        "--reports-dir",
        str(args.reports_dir),
        "--resource-dir",
        str(args.resource_dir),
    ]
    append_selection_args(command, only=args.only, limit=args.limit)
    if args.skip_mapping_gate:
        command.append("--skip-mapping-gate")
    run_command(command)


def build_new(args: argparse.Namespace) -> None:
    """Build new-architecture outputs."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_new_arch_outputs.py"),
        "--input-dir",
        str(args.input_dir),
        "--outputs-dir",
        str(args.new_outputs_dir),
        "--analysis-dir",
        str(args.analysis_dir),
        "--reports-dir",
        str(args.reports_dir),
        "--resource-dir",
        str(args.resource_dir),
        "--ner-max-length",
        str(args.ner_max_length),
    ]
    append_selection_args(command, only=args.only, limit=args.limit)
    if args.ner_model:
        command.extend(["--ner-model", args.ner_model])
    if args.ner_device:
        command.extend(["--ner-device", args.ner_device])
    for threshold in args.ner_threshold:
        command.extend(["--ner-threshold", threshold])
    if args.skip_ner:
        command.append("--skip-ner")
    run_command(command)


def load_json_array(path: Path) -> List[Dict[str, Any]]:
    """Load a schema output JSON array; invalid/missing files become empty lists."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def entity_key(entity: Dict[str, Any], *, include_full: bool = False) -> Tuple[Any, ...]:
    """Return a comparable entity key."""
    pos = entity.get("position") if isinstance(entity.get("position"), list) else [None, None]
    base = (pos[0] if len(pos) > 0 else None, pos[1] if len(pos) > 1 else None, entity.get("type"), entity.get("text"))
    if not include_full:
        return base
    assertions = tuple(sorted(item for item in entity.get("assertions", []) if isinstance(item, str)))
    candidates = tuple(sorted(item for item in entity.get("candidates", []) if isinstance(item, str)))
    return (*base, assertions, candidates)


def counter_for(directory: Path, file_ids: Sequence[str], *, include_full: bool = False) -> Counter:
    """Build a multiset of output entities for a directory."""
    counter: Counter = Counter()
    for file_id in file_ids:
        for entity in load_json_array(directory / f"{file_id}.json"):
            if isinstance(entity, dict):
                counter[(file_id, *entity_key(entity, include_full=include_full))] += 1
    return counter


def output_file_ids(*directories: Path, only: Optional[str], limit: Optional[int]) -> List[str]:
    """Discover file ids from one or more output directories."""
    if only:
        ids = [item.strip() for item in only.split(",") if item.strip()]
    else:
        found = set()
        for directory in directories:
            found.update(path.stem for path in directory.glob("*.json"))
        ids = sorted(found, key=numeric_sort_key)
    if limit is not None:
        ids = ids[:limit]
    return ids


def score_if_gold(args: argparse.Namespace, old_output_dir: Path, new_output_dir: Path) -> Optional[Dict[str, Any]]:
    """Score old/new against gold if gold JSON files exist."""
    if not args.gold_dir.exists() or not any(args.gold_dir.glob("*.json")):
        return None

    file_ids = discover_file_ids(args.gold_dir, new_output_dir, args.limit, args.only)
    old_report = score_directories(args.gold_dir, old_output_dir, args.input_dir, file_ids)
    new_report = score_directories(args.gold_dir, new_output_dir, args.input_dir, file_ids)

    old_md = args.reports_dir / "architecture_old_vs_gold.md"
    new_md = args.reports_dir / "architecture_new_vs_gold.md"
    old_json = args.reports_dir / "architecture_old_vs_gold.json"
    new_json = args.reports_dir / "architecture_new_vs_gold.json"
    write_markdown_report(old_report, old_md, args.gold_dir, old_output_dir)
    write_markdown_report(new_report, new_md, args.gold_dir, new_output_dir)
    write_json_report(old_report, old_json)
    write_json_report(new_report, new_json)

    return {
        "file_ids": file_ids,
        "old_report": old_report,
        "new_report": new_report,
        "old_report_md": old_md,
        "new_report_md": new_md,
        "old_report_json": old_json,
        "new_report_json": new_json,
    }


def metric_delta(old_report: ScoreReport, new_report: ScoreReport) -> Dict[str, Dict[str, float]]:
    """Compute new-minus-old metric deltas."""
    deltas: Dict[str, Dict[str, float]] = {
        "official": {
            "text_score": new_report.official.text_score - old_report.official.text_score,
            "assertions_score": new_report.official.assertions_score - old_report.official.assertions_score,
            "candidates_score": new_report.official.candidates_score - old_report.official.candidates_score,
            "final_score": new_report.official.final_score - old_report.official.final_score,
        }
    }
    for metric_name in sorted(old_report.metrics):
        old = old_report.metrics[metric_name]
        new = new_report.metrics[metric_name]
        deltas[metric_name] = {
            "precision": new.precision - old.precision,
            "recall": new.recall - old.recall,
            "f1": new.f1 - old.f1,
        }
    return deltas


def write_comparison_report(
    *,
    args: argparse.Namespace,
    file_ids: Sequence[str],
    old_output_dir: Path,
    new_output_dir: Path,
    added: Counter,
    removed: Counter,
    added_full: Counter,
    removed_full: Counter,
    gold_scores: Optional[Dict[str, Any]],
) -> None:
    """Write Markdown and JSON architecture comparison reports."""
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Architecture Comparison",
        "",
        f"Old output: `{old_output_dir}`",
        f"New output: `{new_output_dir}`",
        f"Files compared: {len(file_ids)}",
        f"NER: {'enabled: ' + args.ner_model if args.ner_model and not args.skip_ner else 'disabled'}",
        "",
        "## Direct old vs new output diff",
        "",
        f"- Added span/text/type entities in new: {sum(added.values())}",
        f"- Removed span/text/type entities from old: {sum(removed.values())}",
        f"- Added full entities in new: {sum(added_full.values())}",
        f"- Removed full entities from old: {sum(removed_full.values())}",
        "",
    ]

    if gold_scores is not None:
        old_report: ScoreReport = gold_scores["old_report"]
        new_report: ScoreReport = gold_scores["new_report"]
        deltas = metric_delta(old_report, new_report)
        lines.extend(
            [
                "## Gold/silver scoring",
                "",
                "| Metric | Old | New | Delta |",
                "|---|---:|---:|---:|",
                f"| official.final_score | {old_report.official.final_score:.4f} | {new_report.official.final_score:.4f} | {deltas['official']['final_score']:+.4f} |",
                f"| official.text_score | {old_report.official.text_score:.4f} | {new_report.official.text_score:.4f} | {deltas['official']['text_score']:+.4f} |",
                f"| official.assertions_score | {old_report.official.assertions_score:.4f} | {new_report.official.assertions_score:.4f} | {deltas['official']['assertions_score']:+.4f} |",
                f"| official.candidates_score | {old_report.official.candidates_score:.4f} | {new_report.official.candidates_score:.4f} | {deltas['official']['candidates_score']:+.4f} |",
            ]
        )
        for metric_name in sorted(old_report.metrics):
            old = old_report.metrics[metric_name]
            new = new_report.metrics[metric_name]
            lines.append(f"| {metric_name}.f1 | {old.f1:.4f} | {new.f1:.4f} | {new.f1 - old.f1:+.4f} |")
        lines.extend(["", f"Old detailed score report: `{gold_scores['old_report_md']}`", f"New detailed score report: `{gold_scores['new_report_md']}`", ""])
    else:
        deltas = {}
        lines.extend(["## Gold/silver scoring", "", "No gold/silver JSON files found; only direct old-vs-new diff was produced.", ""])

    def add_examples(title: str, values: Counter) -> None:
        lines.extend([f"## {title}", ""])
        if not values:
            lines.append("- None")
            lines.append("")
            return
        for key, count in values.most_common(30):
            lines.append(f"- {count} x `{key}`")
        lines.append("")

    add_examples("Top additions in new", added)
    add_examples("Top removals from old", removed)
    args.report_md.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    json_payload = {
        "old_output_dir": str(old_output_dir),
        "new_output_dir": str(new_output_dir),
        "file_ids": list(file_ids),
        "direct_diff": {
            "added_span_text_type": sum(added.values()),
            "removed_span_text_type": sum(removed.values()),
            "added_full_entity": sum(added_full.values()),
            "removed_full_entity": sum(removed_full.values()),
            "top_added": [{"key": list(key), "count": count} for key, count in added.most_common(100)],
            "top_removed": [{"key": list(key), "count": count} for key, count in removed.most_common(100)],
        },
        "gold_scoring": None if gold_scores is None else {
            "old_report_json": str(gold_scores["old_report_json"]),
            "new_report_json": str(gold_scores["new_report_json"]),
            "metric_delta": deltas,
            "old_official": asdict(gold_scores["old_report"].official),
            "new_official": asdict(gold_scores["new_report"].official),
        },
    }
    args.report_json.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def main() -> int:
    configure_stdout()
    args = parse_args()

    if not args.skip_build_old:
        build_old(args)
    if not args.skip_build_new:
        build_new(args)

    old_output_dir = args.old_outputs_dir / "output"
    new_output_dir = args.new_outputs_dir / "output"
    file_ids = output_file_ids(old_output_dir, new_output_dir, only=args.only, limit=args.limit)
    if not file_ids:
        raise SystemExit("No output JSON files found to compare.")

    old_counter = counter_for(old_output_dir, file_ids, include_full=False)
    new_counter = counter_for(new_output_dir, file_ids, include_full=False)
    old_full = counter_for(old_output_dir, file_ids, include_full=True)
    new_full = counter_for(new_output_dir, file_ids, include_full=True)

    added = new_counter - old_counter
    removed = old_counter - new_counter
    added_full = new_full - old_full
    removed_full = old_full - new_full
    gold_scores = score_if_gold(args, old_output_dir, new_output_dir)

    write_comparison_report(
        args=args,
        file_ids=file_ids,
        old_output_dir=old_output_dir,
        new_output_dir=new_output_dir,
        added=added,
        removed=removed,
        added_full=added_full,
        removed_full=removed_full,
        gold_scores=gold_scores,
    )

    print("=" * 70)
    print("Architecture Comparison Complete")
    print("=" * 70)
    print(f"Files compared: {len(file_ids)}")
    print(f"Added in new: {sum(added.values())}")
    print(f"Removed from old: {sum(removed.values())}")
    if gold_scores is not None:
        old_report: ScoreReport = gold_scores["old_report"]
        new_report: ScoreReport = gold_scores["new_report"]
        print(f"Old official final_score: {old_report.official.final_score:.4f}")
        print(f"New official final_score: {new_report.official.final_score:.4f}")
        print(f"Delta: {new_report.official.final_score - old_report.official.final_score:+.4f}")
    print(f"Saved {args.report_md}")
    print(f"Saved {args.report_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
