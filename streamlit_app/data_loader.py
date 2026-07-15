from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"
DEFAULT_GOLDEN_INPUT_DIR = PROJECT_ROOT / "data" / "golden" / "input"
DEFAULT_GOLD_DIR = PROJECT_ROOT / "data" / "golden" / "gold"
DEFAULT_PHASE9_PRED_DIR = PROJECT_ROOT / "outputs" / "predictions" / "phase9_golden20"
DEFAULT_PHASE9_REPORT_DIR = PROJECT_ROOT / "outputs" / "reports" / "phase9_eval"
DEFAULT_RAW_INPUT_DIR = PROJECT_ROOT / "data" / "raw" / "input"
DEFAULT_SUBMISSION_PRED_DIR = PROJECT_ROOT / "outputs" / "predictions" / "submission_phase9" / "output"
DEFAULT_SUBMISSION_REPORT_DIR = PROJECT_ROOT / "outputs" / "reports" / "submission_phase9_validation"


ERROR_FILES: dict[str, str] = {
    "True positives": "true_positives.jsonl",
    "False positives": "false_positives.jsonl",
    "False negatives": "false_negatives.jsonl",
    "Span mismatches": "span_mismatches.jsonl",
    "Type mismatches": "type_mismatches.jsonl",
    "Assertion mismatches": "assertion_mismatches.jsonl",
    "Candidate mismatches": "candidate_mismatches.jsonl",
    "All error cases": "error_cases.jsonl",
}


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def read_json(path: str | Path, default: Any = None) -> Any:
    resolved = resolve_path(path)
    if not resolved.is_file():
        return default
    return json.loads(resolved.read_text(encoding="utf-8"))


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    resolved = resolve_path(path)
    if not resolved.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in resolved.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_text(path: str | Path) -> str:
    resolved = resolve_path(path)
    return resolved.read_text(encoding="utf-8") if resolved.is_file() else ""


def load_records(directory: str | Path, file_id: str) -> list[dict[str, Any]]:
    data = read_json(resolve_path(directory) / f"{file_id}.json", default=[])
    return data if isinstance(data, list) else []


def load_raw_text(directory: str | Path, file_id: str) -> str:
    return read_text(resolve_path(directory) / f"{file_id}.txt")


def list_file_ids(directory: str | Path, suffix: str = ".txt") -> list[str]:
    resolved = resolve_path(directory)
    if not resolved.is_dir():
        return []
    return [path.stem for path in sorted(resolved.glob(f"*{suffix}"), key=lambda item: natural_key(item.stem))]


def natural_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def load_evaluation_summary(report_dir: str | Path) -> dict[str, Any]:
    data = read_json(resolve_path(report_dir) / "evaluation_summary.json", default={})
    return data if isinstance(data, dict) else {}


def load_csv(report_dir: str | Path, file_name: str) -> pd.DataFrame:
    path = resolve_path(report_dir) / file_name
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_error_rows(report_dir: str | Path, label: str) -> list[dict[str, Any]]:
    file_name = ERROR_FILES.get(label, label)
    return read_jsonl(resolve_path(report_dir) / file_name)


def load_validation_summary(report_dir: str | Path) -> dict[str, Any]:
    data = read_json(resolve_path(report_dir) / "validation_summary.json", default={})
    return data if isinstance(data, dict) else {}


def records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx, record in enumerate(records):
        start, end = get_position(record)
        rows.append(
            {
                "index": idx,
                "text": record.get("text", ""),
                "start": start,
                "end": end,
                "type": record.get("type", ""),
                "assertions": ", ".join(str(item) for item in record.get("assertions", []) or []),
                "candidates": ", ".join(str(item) for item in record.get("candidates", []) or []),
            }
        )
    return pd.DataFrame(rows)


def get_position(record: dict[str, Any]) -> tuple[int, int]:
    position = record.get("position", [0, 0])
    if isinstance(position, list | tuple) and len(position) >= 2:
        try:
            return int(position[0]), int(position[1])
        except (TypeError, ValueError):
            return 0, 0
    return 0, 0


def filter_rows_for_file(rows: list[dict[str, Any]], file_id: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("file_id") or row.get("pred", {}).get("file_id") or row.get("gold", {}).get("file_id")) == str(file_id)]


def summarize_records_by_type(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["type", "count"])
    frame = pd.DataFrame({"type": [record.get("type", "") for record in records]})
    return frame.value_counts("type").reset_index(name="count").sort_values(["count", "type"], ascending=[False, True])
