from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.io_utils import read_text
from src.preprocess.chunker import preprocess_text
from src.preprocess.offset_mapper import map_view_span_to_raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 2 preprocessing/offset smoke checks.")
    parser.add_argument("--config", default="configs/default.yaml", help="Path to YAML config.")
    parser.add_argument("--max-files", type=int, default=4, help="Maximum files to check.")
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    files = _sample_files(config, args.max_files)
    if not files:
        raise FileNotFoundError("No input files found for Phase 2 smoke check")

    total_chunks = 0
    for path in files:
        raw_text = read_text(path, encoding=str(config.raw.get("encoding", "utf-8")))
        output = preprocess_text(raw_text, config.raw)
        _validate_preprocess_output(output.raw_text, output.views, output.chunks, path)
        total_chunks += len(output.chunks)

    print("Phase 2 smoke checks passed.")
    print(f"files_checked: {len(files)}")
    print(f"chunks_created: {total_chunks}")
    return 0


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


def _validate_preprocess_output(raw_text, views, chunks, path: Path) -> None:
    assert views.raw == raw_text, f"Raw view changed for {path}"
    assert len(views.normalized) == len(views.norm_to_raw), f"normalized map length mismatch for {path}"
    assert len(views.search) == len(views.search_to_raw), f"search map length mismatch for {path}"
    assert len(views.no_diacritics) == len(views.no_diacritics_to_raw), f"no-diacritics map mismatch for {path}"
    if views.normalized:
        raw_start, raw_end = map_view_span_to_raw(views.norm_to_raw, 0, 1)
        assert 0 <= raw_start < raw_end <= len(raw_text)
    for chunk in chunks:
        assert 0 <= chunk.start < chunk.end <= len(raw_text), f"Invalid chunk bounds in {path}: {chunk}"
        assert raw_text[chunk.start:chunk.end] == chunk.text, f"Chunk offset mismatch in {path}: {chunk}"


if __name__ == "__main__":
    raise SystemExit(main())
