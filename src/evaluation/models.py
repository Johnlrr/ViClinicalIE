from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvalEntity:
    file_id: str
    text: str
    start: int
    end: int
    type: str
    assertions: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    index: int = 0

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)

    @property
    def exact_key(self) -> tuple[int, int, str]:
        return (self.start, self.end, self.type)

    @property
    def span_len(self) -> int:
        return max(0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "file_id": self.file_id,
            "index": self.index,
            "text": self.text,
            "position": [self.start, self.end],
            "type": self.type,
            "assertions": list(self.assertions),
        }
        if self.candidates:
            record["candidates"] = list(self.candidates)
        return record


@dataclass(slots=True)
class EntityPair:
    pred: EvalEntity
    gold: EvalEntity
    match_kind: str
    span_iou: float = 0.0
    containment_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.gold.file_id or self.pred.file_id,
            "match_kind": self.match_kind,
            "span_iou": self.span_iou,
            "containment_ratio": self.containment_ratio,
            "pred": self.pred.to_dict(),
            "gold": self.gold.to_dict(),
        }


@dataclass(slots=True)
class PRFCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        if denominator == 0:
            return 0.0
        return self.tp / denominator

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        if denominator == 0:
            return 0.0
        return self.tp / denominator

    @property
    def f1(self) -> float:
        precision = self.precision
        recall = self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    def add(self, other: "PRFCounts") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    def to_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
            "f1": round(self.f1, 6),
        }


@dataclass(slots=True)
class EvaluationFileResult:
    file_id: str
    gold_count: int
    pred_count: int
    exact_counts: PRFCounts
    relaxed_counts: PRFCounts
    exact_pairs: list[EntityPair] = field(default_factory=list)
    relaxed_pairs: list[EntityPair] = field(default_factory=list)
    false_positives: list[EvalEntity] = field(default_factory=list)
    false_negatives: list[EvalEntity] = field(default_factory=list)
    span_mismatches: list[dict[str, Any]] = field(default_factory=list)
    type_mismatches: list[dict[str, Any]] = field(default_factory=list)
    assertion_mismatches: list[dict[str, Any]] = field(default_factory=list)
    candidate_mismatches: list[dict[str, Any]] = field(default_factory=list)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "gold_count": self.gold_count,
            "pred_count": self.pred_count,
            "exact": self.exact_counts.to_dict(),
            "relaxed": self.relaxed_counts.to_dict(),
            "span_mismatch_count": len(self.span_mismatches),
            "type_mismatch_count": len(self.type_mismatches),
            "assertion_mismatch_count": len(self.assertion_mismatches),
            "candidate_mismatch_count": len(self.candidate_mismatches),
        }


@dataclass(slots=True)
class EvaluationReport:
    files: list[EvaluationFileResult]
    overall_exact: PRFCounts
    overall_relaxed: PRFCounts
    by_type_exact: dict[str, PRFCounts]
    by_type_relaxed: dict[str, PRFCounts]
    assertion_metrics: dict[str, Any]
    candidate_metrics: dict[str, Any]
    error_category_counts: dict[str, int]
    type_confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    boundary_error_counts: dict[str, int] = field(default_factory=dict)

    @property
    def files_evaluated(self) -> int:
        return len(self.files)

    @property
    def gold_entities(self) -> int:
        return sum(file.gold_count for file in self.files)

    @property
    def pred_entities(self) -> int:
        return sum(file.pred_count for file in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_evaluated": self.files_evaluated,
            "gold_entities": self.gold_entities,
            "pred_entities": self.pred_entities,
            "exact": self.overall_exact.to_dict(),
            "relaxed": self.overall_relaxed.to_dict(),
            "by_type_exact": {key: value.to_dict() for key, value in sorted(self.by_type_exact.items())},
            "by_type_relaxed": {key: value.to_dict() for key, value in sorted(self.by_type_relaxed.items())},
            "assertions": self.assertion_metrics,
            "candidates": self.candidate_metrics,
            "error_category_counts": dict(sorted(self.error_category_counts.items())),
            "type_confusion": self.type_confusion,
            "boundary_error_counts": self.boundary_error_counts,
            "files": [file.to_summary_dict() for file in self.files],
        }