from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import AppConfig, load_config
from src.io_utils import read_json, read_text
from src.logging_utils import create_run_report_dir, write_summary


REQUIRED_PATH_KEYS = (
    "raw_input_dir",
    "icd10_csv",
    "rxnorm_rff",
    "processed_dir",
    "golden_input_dir",
    "golden_gold_dir",
    "prediction_dir",
    "report_dir",
    "submission_dir",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 0 project setup.")
    parser.add_argument(
        "--config",
        default="configs/default.yaml",
        help="Path to the default YAML config.",
    )
    args = parser.parse_args()

    config = load_config(args.config, project_root=PROJECT_ROOT)
    summary = check_setup(config)
    report_dir = create_run_report_dir(
        config.path("report_dir"),
        config,
        run_name="setup_check",
        log_files=config.raw.get("logging", {}).get("log_files"),
    )
    summary["report_dir"] = str(report_dir)
    write_summary(report_dir, summary)

    print("Phase 0 setup check passed.")
    print(f"raw_input_files: {summary['raw_input_files']}")
    print(f"golden_pairs: {summary['golden_pairs']}")
    print(f"golden_entities: {summary['golden_entities']}")
    print(f"report_dir: {report_dir}")
    return 0


def check_setup(config: AppConfig) -> dict[str, Any]:
    _ensure_config_paths(config)
    _ensure_directories(config)

    raw_files = _expected_numbered_files(
        config.path("raw_input_dir"),
        range(1, int(config.raw.get("setup", {}).get("expected_raw_inputs", 100)) + 1),
        ".txt",
    )
    golden_ids = [int(value) for value in config.raw.get("setup", {}).get("golden_ids", range(1, 21))]
    golden_input_files = _expected_numbered_files(config.path("golden_input_dir"), golden_ids, ".txt")
    golden_gold_files = _expected_numbered_files(config.path("golden_gold_dir"), golden_ids, ".json")
    golden_entities = _validate_golden_offsets(
        config.path("golden_input_dir"),
        config.path("golden_gold_dir"),
        golden_ids,
        encoding=str(config.raw.get("encoding", "utf-8")),
    )

    return {
        "status": "passed",
        "raw_input_files": len(raw_files),
        "golden_pairs": min(len(golden_input_files), len(golden_gold_files)),
        "golden_entities": golden_entities,
        "icd10_csv": str(config.path("icd10_csv")),
        "rxnorm_rff": str(config.path("rxnorm_rff")),
    }


def _ensure_config_paths(config: AppConfig) -> None:
    missing_keys = [key for key in REQUIRED_PATH_KEYS if key not in config.paths]
    if missing_keys:
        raise FileNotFoundError(f"Missing required path keys: {', '.join(missing_keys)}")

    required_files = ("icd10_csv", "rxnorm_rff")
    for key in required_files:
        path = config.path(key)
        if not path.is_file():
            raise FileNotFoundError(f"Required file does not exist for '{key}': {path}")


def _ensure_directories(config: AppConfig) -> None:
    existing_dirs = ("raw_input_dir", "golden_input_dir", "golden_gold_dir")
    for key in existing_dirs:
        path = config.path(key)
        if not path.is_dir():
            raise FileNotFoundError(f"Required directory does not exist for '{key}': {path}")

    creatable_dirs = ("processed_dir", "prediction_dir", "report_dir", "submission_dir")
    for key in creatable_dirs:
        config.path(key).mkdir(parents=True, exist_ok=True)


def _expected_numbered_files(directory: Path, ids: range | list[int], suffix: str) -> list[Path]:
    files = []
    missing = []
    for item_id in ids:
        path = directory / f"{item_id}{suffix}"
        if path.exists():
            files.append(path)
        else:
            missing.append(path)
    if missing:
        examples = ", ".join(str(path) for path in missing[:5])
        raise FileNotFoundError(f"Missing expected files: {examples}")
    return files


def _validate_golden_offsets(
    input_dir: Path,
    gold_dir: Path,
    ids: list[int],
    *,
    encoding: str,
) -> int:
    entity_count = 0
    mismatches = []
    for item_id in ids:
        raw_text = read_text(input_dir / f"{item_id}.txt", encoding=encoding)
        entities = read_json(gold_dir / f"{item_id}.json", encoding=encoding)
        if not isinstance(entities, list):
            raise ValueError(f"Gold file must contain a list: {item_id}.json")
        entity_count += len(entities)
        for index, entity in enumerate(entities):
            position = entity.get("position")
            if not isinstance(position, list) or len(position) != 2:
                mismatches.append((item_id, index, "invalid position", position))
                continue
            start, end = position
            if not isinstance(start, int) or not isinstance(end, int):
                mismatches.append((item_id, index, "non-integer position", position))
                continue
            expected = entity.get("text")
            actual = raw_text[start:end]
            if actual != expected:
                mismatches.append((item_id, index, expected, position, actual))

    if mismatches:
        preview = "; ".join(str(item) for item in mismatches[:3])
        raise ValueError(f"Golden offset validation failed: {preview}")
    return entity_count


if __name__ == "__main__":
    raise SystemExit(main())

