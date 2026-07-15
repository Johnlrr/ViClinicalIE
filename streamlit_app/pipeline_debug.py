from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.pipeline import ClinicalIEPipeline, PipelineResult


def build_pipeline(config_path: str | Path, *, enable_sparse_retrieval: bool = False) -> ClinicalIEPipeline:
    config = load_config(config_path, project_root=PROJECT_ROOT)
    return ClinicalIEPipeline(config, enable_sparse_retrieval=enable_sparse_retrieval)


def run_pipeline_on_text(
    raw_text: str,
    *,
    file_id: str,
    config_path: str | Path,
    enable_sparse_retrieval: bool = False,
) -> PipelineResult:
    pipeline = build_pipeline(config_path, enable_sparse_retrieval=enable_sparse_retrieval)
    return pipeline.process_text(raw_text, file_id=file_id)


def postprocess_report_to_dict(report: Any) -> dict[str, Any]:
    if report is None:
        return {}
    output: dict[str, Any] = {}
    for key in (
        "input_count",
        "output_count",
        "exact_duplicates_removed",
        "same_type_overlaps_resolved",
        "different_type_overlaps_resolved",
        "entities_trimmed",
        "entities_dropped",
        "candidate_cleanups",
        "assertion_cleanups",
        "offset_errors",
    ):
        if hasattr(report, key):
            output[key] = getattr(report, key)
    if hasattr(report, "decisions"):
        output["decision_count"] = len(getattr(report, "decisions") or [])
    return output
