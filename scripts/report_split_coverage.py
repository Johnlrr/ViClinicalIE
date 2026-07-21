from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_yaml
from src.io_utils import read_json, read_text, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Report entity/noise coverage for the frozen V2 split.")
    parser.add_argument("--split-config", default="configs/splits_v2.yaml")
    parser.add_argument("--input-dir", default="data/golden/input")
    parser.add_argument("--gold-dir", default="data/golden/gold")
    parser.add_argument("--output", default="outputs/reports/v2_ner_baseline/split_coverage.json")
    args = parser.parse_args()
    config = load_yaml(args.split_config)
    output = {"version": config.get("version"), "splits": {}}
    seen = set()
    for split in ("development", "calibration", "lockbox"):
        ids = [str(value) for value in config[split]["ids"]]
        overlap = seen & set(ids)
        if overlap:
            raise ValueError(f"Split IDs overlap: {sorted(overlap)}")
        seen.update(ids)
        types = collections.Counter()
        lengths = []
        mixed_language = 0
        for file_id in ids:
            text = read_text(Path(args.input_dir) / f"{file_id}.txt")
            records = read_json(Path(args.gold_dir) / f"{file_id}.json")
            types.update(record["type"] for record in records)
            lengths.append(len(text))
            mixed_language += int(any(char.isascii() and char.isalpha() for char in text) and any(ord(char) > 127 for char in text))
        output["splits"][split] = {
            "ids": ids,
            "file_count": len(ids),
            "entity_count": sum(types.values()),
            "entities_by_type": dict(sorted(types.items())),
            "note_length": {"min": min(lengths), "max": max(lengths), "mean": sum(lengths) / len(lengths)},
            "mixed_language_files": mixed_language,
        }
    write_json(args.output, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())