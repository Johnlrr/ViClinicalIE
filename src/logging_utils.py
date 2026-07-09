from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from src.config import AppConfig
from src.io_utils import write_json


DEFAULT_LOG_FILES = (
    "errors.jsonl",
    "span_mismatch.jsonl",
    "no_candidate.jsonl",
    "low_confidence.jsonl",
)


def create_run_report_dir(
    report_dir: str | Path,
    config: AppConfig | Mapping[str, Any],
    *,
    timestamp: str | None = None,
    run_name: str = "run",
    log_files: Iterable[str] | None = None,
) -> Path:
    base_dir = Path(report_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = base_dir / f"{run_name}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    config_payload = _config_payload(config)
    with (run_dir / "config.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config_payload, handle, sort_keys=True, allow_unicode=True)

    write_summary(
        run_dir,
        {
            "status": "initialized",
            "created_at": stamp,
            "run_name": run_name,
        },
    )

    for log_file in log_files or DEFAULT_LOG_FILES:
        (run_dir / log_file).touch()

    return run_dir


def write_summary(run_dir: str | Path, summary: Mapping[str, Any]) -> None:
    write_json(Path(run_dir) / "summary.json", dict(summary))


def _config_payload(config: AppConfig | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(config, AppConfig):
        return config.to_serializable()
    return dict(config)
