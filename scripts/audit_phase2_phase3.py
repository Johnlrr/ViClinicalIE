from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.io_utils import read_json, read_text, write_json
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import detect_sections, load_section_patterns


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Phase 2/3 preprocessing and section detection coverage.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-unmatched", type=int, default=80, help="Number of unmatched heading-like examples to print.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    section_cfg = config.raw.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    files = sorted(config.path("raw_input_dir").glob("*.txt")) + sorted(config.path("golden_input_dir").glob("*.txt"))

    section_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    unmatched_heading_like: list[dict[str, object]] = []
    matched_headings: dict[str, Counter[str]] = defaultdict(Counter)
    offset_errors: list[dict[str, object]] = []
    invalid_sections: list[dict[str, object]] = []

    for path in files:
        raw_text = read_text(path, encoding=str(config.raw.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, config.raw)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        _validate_phase2_maps(path, raw_text, output.views)

        for chunk in chunks:
            if raw_text[chunk.start : chunk.end] != chunk.text:
                offset_errors.append({"file": path.name, "start": chunk.start, "end": chunk.end, "text": chunk.text})
            if not chunk.section:
                invalid_sections.append({"file": path.name, "text": chunk.text[:160]})
            section_counts[str(chunk.section)] += 1
            source_counts[str(chunk.section_source)] += 1

            text = chunk.text.strip()
            prefix = text.split(":", 1)[0].strip() if ":" in text else text
            is_heading_like = len(text) <= 160 and (":" in text[:100] or len(text.split()) <= 8)
            if is_heading_like and chunk.section_source in {"default", "carry_forward"}:
                unmatched_heading_like.append(
                    {
                        "file": path.name,
                        "prefix": prefix[:120],
                        "section": chunk.section,
                        "source": chunk.section_source,
                        "text": text[:180],
                    }
                )
            elif is_heading_like and chunk.section_source and chunk.section_source != "carry_forward":
                matched_headings[str(chunk.section)][prefix[:120]] += 1

    report = {
        "files_checked": len(files),
        "section_counts": dict(sorted(section_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "offset_error_count": len(offset_errors),
        "invalid_section_count": len(invalid_sections),
        "unmatched_heading_like_count": len(unmatched_heading_like),
        "top_unmatched_heading_like": _top_unmatched(unmatched_heading_like, args.max_unmatched),
        "top_matched_headings": {
            section: counter.most_common(20)
            for section, counter in sorted(matched_headings.items())
        },
    }

    report_dir = config.path("report_dir") / "phase2_phase3_audit"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "summary.json", report)

    print("Phase 2/3 audit completed.")
    print(f"files_checked: {report['files_checked']}")
    print(f"offset_error_count: {report['offset_error_count']}")
    print(f"invalid_section_count: {report['invalid_section_count']}")
    print(f"section_counts: {report['section_counts']}")
    print(f"source_counts: {report['source_counts']}")
    print(f"unmatched_heading_like_count: {report['unmatched_heading_like_count']}")
    print("top_unmatched_heading_like:")
    for item in report["top_unmatched_heading_like"][: args.max_unmatched]:
        print(f"  {item['count']} | {item['section']} | {item['source']} | {item['prefix']}")
    print(f"report: {report_dir / 'summary.json'}")
    return 0


def _resolve_patterns_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _validate_phase2_maps(path: Path, raw_text: str, views) -> None:
    if views.raw != raw_text:
        raise AssertionError(f"Raw view changed for {path}")
    if len(views.normalized) != len(views.norm_to_raw):
        raise AssertionError(f"Normalized map length mismatch for {path}")
    if len(views.search) != len(views.search_to_raw):
        raise AssertionError(f"Search map length mismatch for {path}")
    if len(views.no_diacritics) != len(views.no_diacritics_to_raw):
        raise AssertionError(f"No-diacritics map length mismatch for {path}")


def _top_unmatched(items: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    counter: Counter[tuple[str, str, str]] = Counter(
        (str(item["prefix"]), str(item["section"]), str(item["source"]))
        for item in items
    )
    return [
        {"prefix": prefix, "section": section, "source": source, "count": count}
        for (prefix, section, source), count in counter.most_common(limit)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
