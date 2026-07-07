"""Overlap resolution for final V0 span candidates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Dict, Iterable, List, Tuple

from src.models import SpanCandidate
from src.rule_extractors import (
    ENTITY_DIAGNOSIS,
    ENTITY_DRUG,
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_SYMPTOM,
)


TYPE_PRIORITY = {
    ENTITY_LAB_RESULT: 1,
    ENTITY_LAB_NAME: 2,
    ENTITY_DRUG: 3,
    ENTITY_DIAGNOSIS: 4,
    ENTITY_SYMPTOM: 5,
}


def _candidate_key(candidate: SpanCandidate) -> Tuple[str, int, int, str]:
    """Exact duplicate key used before overlap resolution."""
    return (candidate.file_id, candidate.start, candidate.end, candidate.type_candidate)


def _rank(candidate: SpanCandidate) -> Tuple[int, float, int, int]:
    """Lower tuple wins for overlap selection."""
    priority = TYPE_PRIORITY.get(candidate.type_candidate, 99)
    span_len = candidate.end - candidate.start
    return (priority, -candidate.confidence, -span_len, candidate.start)


def _overlaps(candidate: SpanCandidate, accepted: Iterable[SpanCandidate]) -> bool:
    """Return true if candidate overlaps any already accepted span."""
    return any(candidate.start < other.end and other.start < candidate.end for other in accepted)


def merge_candidates(candidates: Iterable[SpanCandidate]) -> List[SpanCandidate]:
    """Dedupe and resolve overlaps, returning accepted output candidates only."""
    best_by_key: Dict[Tuple[str, int, int, str], SpanCandidate] = {}
    for candidate in candidates:
        if not candidate.should_output:
            continue
        key = _candidate_key(candidate)
        previous = best_by_key.get(key)
        if previous is None or _rank(candidate) < _rank(previous):
            best_by_key[key] = candidate

    by_file: Dict[str, List[SpanCandidate]] = defaultdict(list)
    for candidate in best_by_key.values():
        by_file[candidate.file_id].append(candidate)

    accepted: List[SpanCandidate] = []
    for file_id, file_candidates in by_file.items():
        winners: List[SpanCandidate] = []
        for candidate in sorted(file_candidates, key=_rank):
            if _overlaps(candidate, winners):
                continue
            winners.append(
                replace(
                    candidate,
                    span_status="accepted",
                    should_output=True,
                    reject_reason=None,
                )
            )
        accepted.extend(winners)

    return sorted(accepted, key=lambda candidate: (int(candidate.file_id), candidate.start, candidate.end, candidate.type_candidate))
