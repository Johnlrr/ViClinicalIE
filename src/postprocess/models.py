from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.data_types import FinalEntity


@dataclass(slots=True)
class PostprocessDecision:
    action: str
    reason: str
    kept: dict[str, Any] | None = None
    removed: list[dict[str, Any]] = field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@dataclass(slots=True)
class PostprocessReport:
    input_count: int
    output_count: int = 0
    exact_duplicates_removed: int = 0
    same_type_overlaps_resolved: int = 0
    different_type_overlaps_resolved: int = 0
    entities_trimmed: int = 0
    entities_dropped: int = 0
    candidate_cleanups: int = 0
    assertion_cleanups: int = 0
    offset_errors: list[str] = field(default_factory=list)
    decisions: list[PostprocessDecision] = field(default_factory=list)


@dataclass(slots=True)
class PostprocessResult:
    entities: list[FinalEntity]
    report: PostprocessReport
