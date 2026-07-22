from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.data_types import FinalEntity, SpanCandidate
from src.ner.evidence_adapter import candidate_evidence_row
from src.type_resolution import TypeResolver


V1_SOURCES = frozenset({"dictionary", "drug_rule", "lab_rule", "lab_result_rule", "imaging_rule", "problem_rule"})
STRUCTURED_ANCHOR_TYPES = {
    "drug_rule": frozenset({"THUỐC"}),
    "lab_rule": frozenset({"TÊN_XÉT_NGHIỆM"}),
    "lab_result_rule": frozenset({"KẾT_QUẢ_XÉT_NGHIỆM"}),
    "imaging_rule": frozenset({"TÊN_XÉT_NGHIỆM"}),
}
DEFAULT_ANCHOR_SOURCE_PRIORITY = {"lab_result_rule": 100, "lab_rule": 95, "imaging_rule": 90, "drug_rule": 85}


@dataclass(slots=True)
class FusionResult:
    entities: list[FinalEntity]
    candidates: list[SpanCandidate]
    anchor_events: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[Any] = field(default_factory=list)
    overlaps: list[Any] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    duplicate_exact_span_count: int = 0


def source_subset(candidates: list[SpanCandidate], mode: str) -> list[SpanCandidate]:
    if mode == "v1":
        return [candidate for candidate in candidates if candidate.source in V1_SOURCES]
    if mode == "gliner":
        return [candidate for candidate in candidates if candidate.source == "gliner"]
    if mode in {"naive_union", "simple_fusion"}:
        return [candidate for candidate in candidates if candidate.source == "gliner" or candidate.source in V1_SOURCES]
    raise ValueError(f"Unknown NER-3 replay mode: {mode}")


def resolve_replay(
    candidates: list[SpanCandidate], raw_text: str, *, mode: str,
    resolver_config: Mapping[str, Any] | None = None, fusion_config: Mapping[str, Any] | None = None,
) -> list[FinalEntity]:
    return resolve_replay_trace(
        candidates, raw_text, mode=mode, resolver_config=resolver_config, fusion_config=fusion_config,
    ).entities


def resolve_replay_trace(
    candidates: list[SpanCandidate], raw_text: str, *, mode: str,
    resolver_config: Mapping[str, Any] | None = None, fusion_config: Mapping[str, Any] | None = None,
) -> FusionResult:
    selected = source_subset(candidates, mode)
    if mode == "naive_union":
        v1 = TypeResolver(resolver_config).resolve(source_subset(selected, "v1"), raw_text)
        gliner = TypeResolver(resolver_config).resolve(source_subset(selected, "gliner"), raw_text)
        return FusionResult(merge_exact_entities([*v1, *gliner]), selected)

    anchor_events: list[dict[str, Any]] = []
    if mode == "simple_fusion":
        selected, anchor_events = apply_structured_anchors(selected, raw_text, config=fusion_config)
    effective_resolver_config = dict(resolver_config or {})
    if mode == "simple_fusion":
        effective_resolver_config["resolve_exact_span_conflicts"] = True
    resolver = TypeResolver(effective_resolver_config)
    entities = resolver.resolve(selected, raw_text)
    if mode == "simple_fusion":
        entities = merge_exact_entities(entities)
    _mark_fusion_entities(entities, mode, anchor_events)
    return FusionResult(
        entities=entities, candidates=selected, anchor_events=anchor_events,
        conflicts=list(resolver.conflicts), overlaps=list(resolver.overlaps),
        unresolved=list(resolver.unresolved), duplicate_exact_span_count=resolver.duplicate_exact_span_count,
    )


def apply_structured_anchors(
    candidates: list[SpanCandidate], raw_text: str, *, config: Mapping[str, Any] | None = None,
) -> tuple[list[SpanCandidate], list[dict[str, Any]]]:
    cfg = dict(config or {})
    if not bool(cfg.get("structured_anchors_enabled", True)):
        return list(candidates), []
    priority = {**DEFAULT_ANCHOR_SOURCE_PRIORITY, **dict(cfg.get("anchor_source_priority", {}))}
    gliner = [(index, item) for index, item in enumerate(candidates) if item.source == "gliner"]
    experts = [(index, item) for index, item in enumerate(candidates) if _is_allowed_anchor(item)]
    edges: list[tuple[tuple[Any, ...], int, int]] = []
    for gliner_index, semantic in gliner:
        for expert_index, expert in experts:
            if semantic.raw_type != expert.raw_type or not _strict_containment(semantic, expert):
                continue
            overlap = _overlap(semantic, expert)
            union = max(semantic.end, expert.end) - min(semantic.start, expert.start)
            iou = overlap / union if union else 0.0
            rank = (-priority.get(expert.source, 0), -iou, expert.start, expert.end, expert.source, gliner_index, expert_index)
            edges.append((rank, gliner_index, expert_index))

    used_gliner: set[int] = set()
    evidence_by_anchor: dict[int, list[SpanCandidate]] = defaultdict(list)
    events: list[dict[str, Any]] = []
    for _, gliner_index, expert_index in sorted(edges):
        if gliner_index in used_gliner:
            continue
        semantic, expert = candidates[gliner_index], candidates[expert_index]
        used_gliner.add(gliner_index)
        evidence_by_anchor[expert_index].append(semantic)
        events.append({
            "type": semantic.raw_type, "expert_source": expert.source,
            "gliner_span": [semantic.start, semantic.end], "anchor_span": [expert.start, expert.end],
            "relation": "expert_contains_gliner" if _contains(expert, semantic) else "gliner_contains_expert",
            "selected_span": [expert.start, expert.end],
        })

    output: list[SpanCandidate] = []
    for index, candidate in enumerate(candidates):
        if index in used_gliner:
            continue
        supporting = evidence_by_anchor.get(index)
        if not supporting:
            output.append(candidate)
            continue
        features = deepcopy(candidate.features)
        features["ner3_structured_anchor"] = {
            "selected_anchor": candidate_evidence_row(candidate),
            "semantic_proposals": [candidate_evidence_row(item) for item in sorted(supporting, key=_candidate_sort_key)],
        }
        output.append(_copy_candidate(candidate, features))
    return sorted(output, key=_candidate_sort_key), sorted(events, key=lambda row: (row["selected_span"], row["type"], row["expert_source"]))


def merge_exact_entities(entities: list[FinalEntity]) -> list[FinalEntity]:
    grouped: dict[tuple[int, int, str], list[FinalEntity]] = defaultdict(list)
    for entity in entities:
        grouped[(entity.start, entity.end, str(entity.type))].append(entity)
    output: list[FinalEntity] = []
    for key in sorted(grouped):
        group = grouped[key]
        winner = max(group, key=lambda item: (item.confidence, str(item.provenance.get("chosen_source", ""))))
        provenance = deepcopy(winner.provenance)
        evidence: list[dict] = []
        for entity in group:
            rows = entity.provenance.get("source_candidates", [])
            evidence.extend(deepcopy(rows) if isinstance(rows, list) else [])
        provenance["source_candidates"] = sorted(evidence, key=_source_candidate_sort_key)
        contributing_sources = {
            str(row.get("source", "")) for row in evidence if isinstance(row, Mapping)
        } | {str(entity.provenance.get("chosen_source", "")) for entity in group}
        provenance["ner3_exact_sources"] = sorted(contributing_sources - {""})
        provenance.setdefault("ner3_fusion_mode", "naive_union_exact_dedup")
        output.append(FinalEntity(
            text=winner.text, start=winner.start, end=winner.end, type=winner.type,
            assertions=list(winner.assertions), candidates=list(winner.candidates),
            confidence=winner.confidence, provenance=provenance,
        ))
    return output


def _mark_fusion_entities(entities: list[FinalEntity], mode: str, events: list[dict[str, Any]]) -> None:
    by_span: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_span[tuple(event["selected_span"])].append(event)
    for entity in entities:
        entity.provenance["ner3_fusion_mode"] = mode
        if by_span.get((entity.start, entity.end)):
            entity.provenance["ner3_structured_anchor_events"] = deepcopy(by_span[(entity.start, entity.end)])


def _is_allowed_anchor(candidate: SpanCandidate) -> bool:
    return str(candidate.raw_type) in STRUCTURED_ANCHOR_TYPES.get(candidate.source, frozenset())


def _strict_containment(first: SpanCandidate, second: SpanCandidate) -> bool:
    return (first.start, first.end) != (second.start, second.end) and (_contains(first, second) or _contains(second, first))


def _contains(first: SpanCandidate, second: SpanCandidate) -> bool:
    return first.start <= second.start and first.end >= second.end


def _overlap(first: SpanCandidate, second: SpanCandidate) -> int:
    return max(0, min(first.end, second.end) - max(first.start, second.start))


def _copy_candidate(candidate: SpanCandidate, features: dict[str, Any]) -> SpanCandidate:
    return SpanCandidate(
        candidate.text, candidate.start, candidate.end, candidate.raw_type, candidate.source, candidate.score,
        section=candidate.section, subsection=candidate.subsection,
        context_left=candidate.context_left, context_right=candidate.context_right, features=features,
    )


def _candidate_sort_key(item: SpanCandidate) -> tuple[Any, ...]:
    import json
    return (
        item.start, item.end, item.source, item.raw_type or "", -item.score, item.text,
        json.dumps(item.features, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _source_candidate_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(row.get("source", "")), str(row.get("raw_type", "")), -float(row.get("score", 0.0)))