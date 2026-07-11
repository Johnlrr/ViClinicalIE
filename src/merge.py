"""Overlap resolution for final V0 span candidates.

Follows Sections 2, 4-7, 10-11 of ``2_dictionary_rules.md``:

- Exact-duplicate (same start/end/type) candidates from different sources are
  *merged* into one candidate with combined source tags and the best trace.
- Overlapping candidates are resolved by a source-aware rank that prefers
  specialized-parser evidence over NER over dictionary over structural fallback.
- Structural fallback (confidence 0.40) is only kept when no better candidate
  exists for the same region.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.models import SpanCandidate
from src.rule_extractors import (
    ENTITY_DIAGNOSIS,
    ENTITY_DRUG,
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_SYMPTOM,
    RELIABILITY_SPECIALIZED_PARSER,
    RELIABILITY_SEMANTIC_NER,
    RELIABILITY_CONTEXTUAL_DICTIONARY,
    RELIABILITY_EXACT_CURATED_ALIAS,
    RELIABILITY_STRUCTURED_PATTERN,
    RELIABILITY_SUBSTRING_MATCH,
    RELIABILITY_STRUCTURAL_FALLBACK,
)

# ---------------------------------------------------------------------------
# Source reliability rank (lower = more reliable)
# ---------------------------------------------------------------------------

SOURCE_RELIABILITY_RANK: Dict[str, int] = {
    "drug_parser": 1,
    "lab_parser": 1,
    "boundary_composition": 2,
    "dose_parser": 2,
    "local_structure": 2,
    "rxnorm_prelink": 3,
    "vihealthbert_ner": 4,
    "lab_dictionary": 5,
    "drug_dictionary": 5,
    "diagnosis_dictionary": 5,
    "symptom_dictionary": 5,
    "section_rule": 6,
    "lab_regex": 7,
    "non_target_dictionary": 8,
    "rxnorm_catalog": 9,
    "structural_fallback": 20,
}

RELIABILITY_TIER_RANK: Dict[str, int] = {
    RELIABILITY_SPECIALIZED_PARSER: 1,
    RELIABILITY_SEMANTIC_NER: 2,
    RELIABILITY_CONTEXTUAL_DICTIONARY: 3,
    RELIABILITY_EXACT_CURATED_ALIAS: 4,
    RELIABILITY_STRUCTURED_PATTERN: 5,
    RELIABILITY_SUBSTRING_MATCH: 6,
    RELIABILITY_STRUCTURAL_FALLBACK: 10,
}

TYPE_PRIORITY = {
    ENTITY_LAB_RESULT: 1,
    ENTITY_LAB_NAME: 2,
    ENTITY_DRUG: 3,
    ENTITY_DIAGNOSIS: 4,
    ENTITY_SYMPTOM: 5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate_key(candidate: SpanCandidate) -> Tuple[str, int, int, str]:
    """Exact duplicate key for (start, end, type) merge grouping."""
    return (candidate.file_id, candidate.start, candidate.end, candidate.type_candidate)


def _source_rank(candidate: SpanCandidate) -> int:
    """Aggregate source rank from explicit source tags and trace notes."""
    rank = 99
    for tag in candidate.source:
        rank = min(rank, SOURCE_RELIABILITY_RANK.get(tag, 99))
    # If notes contains a trace, also inspect reliability_tier.
    if candidate.notes:
        try:
            trace = json.loads(candidate.notes)
        except (json.JSONDecodeError, TypeError):
            trace = {}
        tier = trace.get("reliability_tier", "")
        if tier:
            rank = min(rank, RELIABILITY_TIER_RANK.get(tier, 99))
    return rank


def _merge_sources(
    keep: SpanCandidate,
    other: SpanCandidate,
) -> SpanCandidate:
    """Combine sources, confidence, trace of two candidates sharing exact span/type.

    The *keep* candidate is the primary; we merge ``other``'s source tags,
    mapping candidates, and update confidence when the other has stronger
    evidence. Trace notes from the stronger source are preserved.
    """
    # --- sources ----------------------------------------
    merged_sources = list(dict.fromkeys(keep.source + other.source))

    # --- mapping candidates -----------------------------
    merged_mapping = list(dict.fromkeys(
        (keep.mapping_candidates or []) + (other.mapping_candidates or []),
    ))

    # --- confidence ------------------------------------
    # Take the higher confidence, modulated by source rank:
    # a lower-ranked source should not push confidence too high.
    keep_rank = _source_rank(keep)
    other_rank = _source_rank(other)
    if other_rank < keep_rank and other.confidence > keep.confidence:
        # Other is more reliable – lean toward its confidence.
        merged_conf = round((other.confidence * 0.7 + keep.confidence * 0.3), 4)
    elif other.confidence > keep.confidence:
        # Same or lower rank but higher confidence – modest bump.
        merged_conf = round(max(keep.confidence, other.confidence), 4)
    else:
        merged_conf = keep.confidence

    # --- notes / trace ---------------------------------
    # Keep the trace from the more reliable source.
    merged_notes = keep.notes
    if other_rank < keep_rank and other.notes:
        merged_notes = other.notes
    elif not merged_notes and other.notes:
        merged_notes = other.notes

    return replace(
        keep,
        source=merged_sources,
        confidence=merged_conf,
        mapping_candidates=merged_mapping,
        notes=merged_notes,
    )


def _rank(candidate: SpanCandidate) -> Tuple[int, float, int, int, int]:
    """Lower tuple wins for overlap selection.

    Prioritises source reliability, then confidence, span length,
    then start position. Structural fallback is explicitly penalised.
    """
    source_r = _source_rank(candidate)
    # Heavy penalty for structural fallback.
    if source_r >= SOURCE_RELIABILITY_RANK.get("structural_fallback", 20):
        structural_penalty = 3
    else:
        structural_penalty = 0
    span_len = candidate.end - candidate.start
    priority = TYPE_PRIORITY.get(candidate.type_candidate, 99)
    return (
        source_r + structural_penalty,
        -candidate.confidence,
        -span_len,
        candidate.start,
        priority,
    )


def _overlaps(candidate: SpanCandidate, accepted: Iterable[SpanCandidate]) -> bool:
    """Return true if *candidate* overlaps any already accepted span."""
    return any(
        candidate.start < other.end and other.start < candidate.end
        for other in accepted
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def merge_candidates(candidates: Iterable[SpanCandidate]) -> List[SpanCandidate]:
    """Dedupe, merge duplicate sources, and resolve overlaps.

    1. Group exact-duplicate candidates (same file_id, start, end, type)
       and *merge* their sources/confidence/trace rather than discarding.
    2. Within each file, overlap-resolve using a source-aware rank.
    3. Structural fallback candidates (confidence 0.40) survive only
       when no better candidate occupies their span region.
    """
    # Step 1 — group exact duplicates and merge sources.
    groups: Dict[Tuple[str, int, int, str], List[SpanCandidate]] = defaultdict(list)
    for candidate in candidates:
        if not candidate.should_output:
            continue
        key = _candidate_key(candidate)
        groups[key].append(candidate)

    merged: List[SpanCandidate] = []
    for candidates_in_group in groups.values():
        if len(candidates_in_group) == 1:
            merged.append(candidates_in_group[0])
        else:
            # Keep the highest-confidence candidate as base, merge others' sources.
            primary = max(candidates_in_group, key=lambda c: c.confidence)
            for other in candidates_in_group:
                if other is primary:
                    continue
                primary = _merge_sources(primary, other)
            merged.append(primary)

    # Step 2 — per-file overlap resolution.
    by_file: Dict[str, List[SpanCandidate]] = defaultdict(list)
    for candidate in merged:
        by_file[candidate.file_id].append(candidate)

    accepted: List[SpanCandidate] = []
    for _file_id, file_candidates in by_file.items():
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

    # Final sort for deterministic output.
    return sorted(
        accepted,
        key=lambda c: (c.file_id, c.start, c.end, c.type_candidate),
    )
