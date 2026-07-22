from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.data_types import SpanCandidate


EXPERT_SOURCES = ("dictionary", "drug_rule", "lab_rule", "lab_result_rule", "imaging_rule", "problem_rule")


@dataclass(frozen=True, slots=True)
class ComplementarityMatch:
    category: str
    first_index: int | None
    second_index: int | None
    first_source: str | None
    second_source: str | None
    first_type: str | None
    second_type: str | None
    iou: float


def analyze_complementarity(
    gliner: list[SpanCandidate], experts: list[SpanCandidate], *, near_iou_threshold: float = 0.5,
    gold_records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    gliner = _canonical_candidates(gliner)
    experts = _canonical_candidates(experts)
    matches = _match(gliner, experts, near_iou_threshold=near_iou_threshold)
    category_counts = Counter(match.category for match in matches)
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for match in matches:
        for entity_type in {match.first_type, match.second_type} - {None}:
            by_type[str(entity_type)][match.category] += 1
    anchors = structured_anchor_opportunities(gliner, experts)
    by_source: dict[str, Any] = {}
    for source in EXPERT_SOURCES:
        subset = [candidate for candidate in experts if candidate.source == source]
        pair_matches = _match(gliner, subset, near_iou_threshold=near_iou_threshold)
        by_source[source] = {
            "gliner_candidate_count": len(gliner),
            "expert_candidate_count": len(subset),
            "categories": dict(sorted(Counter(item.category for item in pair_matches).items())),
            "gold_utility": source_gold_utility(subset, gold_records or (), near_iou_threshold=near_iou_threshold),
        }
    return {
        "category_counts": dict(sorted(category_counts.items())),
        "by_type": {key: dict(sorted(value.items())) for key, value in sorted(by_type.items())},
        "by_source": by_source,
        "gold_utility": {
            "gliner": source_gold_utility(gliner, gold_records or (), near_iou_threshold=near_iou_threshold),
            "v1_aggregated": source_gold_utility(experts, gold_records or (), near_iou_threshold=near_iou_threshold),
        },
        "structured_anchor_opportunities": anchors,
        "matches": [asdict(match) for match in matches],
    }


def source_gold_utility(
    candidates: Sequence[SpanCandidate], gold_records: Sequence[Mapping[str, Any]], *, near_iou_threshold: float = 0.5,
) -> dict[str, Any]:
    canonical = _canonical_candidates(candidates)
    gold = [row for item in gold_records if (row := _gold_span(item)) is not None]
    exact_tp, relaxed_tp = _gold_match_count(canonical, gold, near_iou_threshold)
    by_type: dict[str, dict[str, int]] = {}
    for entity_type in sorted({str(row[2]) for row in gold} | {str(item.raw_type) for item in canonical}):
        subset = [item for item in canonical if str(item.raw_type) == entity_type]
        subset_gold = [row for row in gold if row[2] == entity_type]
        type_exact, type_relaxed = _gold_match_count(subset, subset_gold, near_iou_threshold)
        by_type[entity_type] = {
            "candidate_count": len(subset), "exact_gold_tp": type_exact, "relaxed_gold_tp": type_relaxed,
            "source_only_fp": len(subset) - type_exact, "unrecovered_gold": len(subset_gold) - type_exact,
        }
    return {
        "candidate_count": len(canonical), "exact_gold_tp": exact_tp, "relaxed_gold_tp": relaxed_tp,
        "source_only_fp": len(canonical) - exact_tp, "unrecovered_gold": len(gold) - exact_tp,
        "by_type": by_type,
    }


def structured_anchor_opportunities(gliner: list[SpanCandidate], experts: list[SpanCandidate]) -> list[dict[str, Any]]:
    allowed = {
        "drug_rule": {"THUỐC"}, "lab_rule": {"TÊN_XÉT_NGHIỆM"},
        "lab_result_rule": {"KẾT_QUẢ_XÉT_NGHIỆM"}, "imaging_rule": {"TÊN_XÉT_NGHIỆM"},
    }
    output: list[dict[str, Any]] = []
    for gliner_index, semantic in enumerate(gliner):
        for expert_index, expert in enumerate(experts):
            if semantic.raw_type not in allowed.get(expert.source, set()) or semantic.raw_type != expert.raw_type:
                continue
            if not _overlap(semantic, expert) or semantic.start == expert.start and semantic.end == expert.end:
                continue
            if not (_contains(semantic, expert) or _contains(expert, semantic)):
                continue
            output.append({
                "gliner_index": gliner_index, "expert_index": expert_index,
                "type": semantic.raw_type, "expert_source": expert.source,
                "gliner_span": [semantic.start, semantic.end], "expert_span": [expert.start, expert.end],
                "relation": "expert_contains_gliner" if _contains(expert, semantic) else "gliner_contains_expert",
            })
    return sorted(output, key=lambda row: (row["gliner_span"], row["expert_span"], row["expert_source"]))


def _match(first: list[SpanCandidate], second: list[SpanCandidate], *, near_iou_threshold: float) -> list[ComplementarityMatch]:
    edges: list[tuple[tuple[int, float, int, int], int, int, str, float]] = []
    for first_index, left in enumerate(first):
        for second_index, right in enumerate(second):
            iou = _iou(left, right)
            if left.start == right.start and left.end == right.end:
                category = "exact_agreement" if left.raw_type == right.raw_type else "exact_type_conflict"
                rank = 0 if category == "exact_agreement" else 1
            elif iou >= near_iou_threshold:
                category = "near_overlap_agreement" if left.raw_type == right.raw_type else "near_overlap_type_conflict"
                rank = 2 if category == "near_overlap_agreement" else 3
            else:
                continue
            edges.append(((rank, -iou, first_index, second_index), first_index, second_index, category, iou))
    used_first: set[int] = set()
    used_second: set[int] = set()
    output: list[ComplementarityMatch] = []
    for _, first_index, second_index, category, iou in sorted(edges):
        if first_index in used_first or second_index in used_second:
            continue
        used_first.add(first_index); used_second.add(second_index)
        left, right = first[first_index], second[second_index]
        output.append(ComplementarityMatch(category, first_index, second_index, left.source, right.source, left.raw_type, right.raw_type, iou))
    for index, candidate in enumerate(first):
        if index not in used_first:
            output.append(ComplementarityMatch("gliner_only", index, None, candidate.source, None, candidate.raw_type, None, 0.0))
    for index, candidate in enumerate(second):
        if index not in used_second:
            output.append(ComplementarityMatch("v1_only", None, index, None, candidate.source, None, candidate.raw_type, 0.0))
    return output


def _canonical_candidates(candidates: Iterable[SpanCandidate]) -> list[SpanCandidate]:
    unique: dict[tuple[Any, ...], SpanCandidate] = {}
    for item in candidates:
        key = (item.start, item.end, item.raw_type, item.source)
        previous = unique.get(key)
        if previous is None or item.score > previous.score:
            unique[key] = item
    return sorted(unique.values(), key=lambda item: (item.start, item.end, item.source, item.raw_type or "", -item.score))


def _gold_match_count(
    candidates: Sequence[SpanCandidate], gold: Sequence[tuple[int, int, str]], threshold: float,
) -> tuple[int, int]:
    used_exact: set[int] = set(); used_relaxed: set[int] = set()
    exact_tp = 0; relaxed_tp = 0
    for candidate in candidates:
        exact_index = next((i for i, row in enumerate(gold) if i not in used_exact and _exact_gold(candidate, row)), None)
        if exact_index is not None:
            used_exact.add(exact_index); exact_tp += 1
        ranked = sorted(
            ((-_gold_iou(candidate, row), i) for i, row in enumerate(gold) if i not in used_relaxed and str(candidate.raw_type) == row[2]),
        )
        if ranked and -ranked[0][0] >= threshold:
            used_relaxed.add(ranked[0][1]); relaxed_tp += 1
    return exact_tp, relaxed_tp


def _gold_span(row: Mapping[str, Any]) -> tuple[int, int, str] | None:
    position = row.get("position")
    if not isinstance(position, Sequence) or isinstance(position, (str, bytes)) or len(position) != 2:
        return None
    return int(position[0]), int(position[1]), str(row.get("type", ""))


def _exact_gold(candidate: SpanCandidate, gold: tuple[int, int, str]) -> bool:
    return (candidate.start, candidate.end, str(candidate.raw_type)) == gold


def _gold_iou(candidate: SpanCandidate, gold: tuple[int, int, str]) -> float:
    overlap = max(0, min(candidate.end, gold[1]) - max(candidate.start, gold[0]))
    union = (candidate.end - candidate.start) + (gold[1] - gold[0]) - overlap
    return overlap / union if union else 0.0


def _overlap(first: SpanCandidate, second: SpanCandidate) -> int:
    return max(0, min(first.end, second.end) - max(first.start, second.start))


def _contains(first: SpanCandidate, second: SpanCandidate) -> bool:
    return first.start <= second.start and first.end >= second.end


def _iou(first: SpanCandidate, second: SpanCandidate) -> float:
    overlap = _overlap(first, second)
    union = (first.end - first.start) + (second.end - second.start) - overlap
    return overlap / union if union else 0.0