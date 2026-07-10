from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.io_utils import read_text
from src.preprocess.chunker import preprocess_text
from src.section.section_detector import SECTION_LABELS, detect_sections, load_section_patterns


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 3 section detection smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=4, help="Maximum files to check.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    section_cfg = config.raw.get("section_detection", {})
    patterns_path = _resolve_patterns_path(config.config_path, section_cfg.get("patterns_config", "section_patterns.yaml"))
    patterns = load_section_patterns(patterns_path)
    files = _sample_files(config, args.max_files)
    if not files:
        raise FileNotFoundError("No input files found for Phase 3 smoke check")

    total_chunks = 0
    section_counts: Counter[str] = Counter()
    for path in files:
        raw_text = read_text(path, encoding=str(config.raw.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, config.raw)
        chunks = detect_sections(output.chunks, patterns, section_cfg)
        _validate_sectioned_chunks(raw_text, chunks, path)
        total_chunks += len(chunks)
        section_counts.update(str(chunk.section) for chunk in chunks)

    print("Phase 3 smoke checks passed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_checked: {total_chunks}")
    print(f"section_counts: {dict(sorted(section_counts.items()))}")
    return 0


def _resolve_patterns_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return config_path.parent / path


def _sample_files(config, max_files: int) -> list[Path]:
    candidates: list[Path] = []
    for key in ("raw_input_dir", "golden_input_dir"):
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


def _validate_sectioned_chunks(raw_text: str, chunks, path: Path) -> None:
    for chunk in chunks:
        assert raw_text[chunk.start:chunk.end] == chunk.text, f"Chunk offset mismatch in {path}: {chunk}"
        assert chunk.section in SECTION_LABELS, f"Invalid section label in {path}: {chunk.section}"
        assert chunk.section_confidence >= 0.0, f"Negative section confidence in {path}: {chunk}"
        assert chunk.section_source, f"Missing section source in {path}: {chunk}"


if __name__ == "__main__":
    raise SystemExit(main())
