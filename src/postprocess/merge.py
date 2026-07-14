from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from src.data_types import FinalEntity
from src.postprocess.models import PostprocessDecision
from src.postprocess.policies import dedupe_stable, entity_rank, ordered_valid_assertions, type_priority
from src.postprocess.span_utils import contains, entity_key, entity_payload, overlaps, span_iou, span_len


def merge_exact_duplicates(
    entities: list[FinalEntity],
    raw_text: str,
    config: dict[str, Any],
) -> tuple[list[FinalEntity], list[PostprocessDecision]]:
    del raw_text
    merge_cfg = config.get("merge", {}) if isinstance(config.get("merge"), dict) else {}
    if not bool(merge_cfg.get("remove_exact_duplicates", True)):
        return entities, []
    grouped: dict[tuple[int, int, str], list[FinalEntity]] = defaultdict(list)
    for entity in entities:
        grouped[entity_key(entity)].append(entity)

    output: list[FinalEntity] = []
    decisions: list[PostprocessDecision] = []
    for group in grouped.values():
        if len(group) == 1:
            output.append(group[0])
            continue
        winner = _choose_best(group, config)
        merged = _merge_group_fields(winner, group)
        output.append(merged)
        decisions.append(
            PostprocessDecision(
                action="merge_exact_duplicates",
                reason="same_start_end_type",
                kept=entity_payload(merged),
                removed=[entity_payload(item) for item in group if item is not winner],
            )
        )
    return sorted(output, key=lambda item: (item.start, item.end, str(item.type))), decisions


def resolve_same_type_overlaps(
    entities: list[FinalEntity],
    raw_text: str,
    config: dict[str, Any],
) -> tuple[list[FinalEntity], list[PostprocessDecision]]:
    del raw_text
    merge_cfg = config.get("merge", {}) if isinstance(config.get("merge"), dict) else {}
    iou_threshold = float(merge_cfg.get("same_type_iou_threshold", 0.80))
    output = list(sorted(entities, key=lambda item: (item.start, item.end, str(item.type))))
    decisions: list[PostprocessDecision] = []
    changed = True
    while changed:
        changed = False
        for i, first in enumerate(output):
            for j in range(i + 1, len(output)):
                second = output[j]
                if second.start >= first.end:
                    break
                if str(first.type) != str(second.type) or not overlaps(first, second):
                    continue
                if not _same_type_should_resolve(first, second, iou_threshold):
                    continue
                keep, drop = _choose_overlap_winner(first, second, config)
                keep = _mark_overlap_resolution(keep, "same_type_overlap", [drop])
                if drop is second:
                    output[i] = keep
                    output.pop(j)
                else:
                    output[j] = keep
                    output.pop(i)
                decisions.append(
                    PostprocessDecision(
                        action="resolve_same_type_overlap",
                        reason=f"same_type_overlap_iou={span_iou(first, second):.3f}",
                        kept=entity_payload(keep),
                        removed=[entity_payload(drop)],
                    )
                )
                changed = True
                break
            if changed:
                break
    return output, decisions


def resolve_different_type_overlaps(
    entities: list[FinalEntity],
    raw_text: str,
    config: dict[str, Any],
) -> tuple[list[FinalEntity], list[PostprocessDecision]]:
    del raw_text
    merge_cfg = config.get("merge", {}) if isinstance(config.get("merge"), dict) else {}
    if not bool(merge_cfg.get("resolve_different_type_overlaps", True)):
        return entities, []
    output = list(sorted(entities, key=lambda item: (item.start, item.end, str(item.type))))
    decisions: list[PostprocessDecision] = []
    changed = True
    while changed:
        changed = False
        for i, first in enumerate(output):
            for j in range(i + 1, len(output)):
                second = output[j]
                if second.start >= first.end:
                    break
                if str(first.type) == str(second.type) or not overlaps(first, second):
                    continue
                decision = _different_type_decision(first, second, config)
                if decision is None:
                    continue
                keep, drop, reason = decision
                keep = _mark_overlap_resolution(keep, reason, [drop])
                if drop is second:
                    output[i] = keep
                    output.pop(j)
                else:
                    output[j] = keep
                    output.pop(i)
                decisions.append(
                    PostprocessDecision(
                        action="resolve_different_type_overlap",
                        reason=reason,
                        kept=entity_payload(keep),
                        removed=[entity_payload(drop)],
                    )
                )
                changed = True
                break
            if changed:
                break
    return output, decisions


def remaining_overlap_count(entities: list[FinalEntity]) -> int:
    count = 0
    ordered = sorted(entities, key=lambda item: (item.start, item.end))
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            if second.start >= first.end:
                break
            if overlaps(first, second):
                count += 1
    return count


def _choose_best(group: list[FinalEntity], config: dict[str, Any]) -> FinalEntity:
    return sorted(group, key=lambda item: entity_rank(item, config), reverse=True)[0]


def _merge_group_fields(winner: FinalEntity, group: list[FinalEntity]) -> FinalEntity:
    assertions: list[str] = []
    candidates: list[str] = []
    for item in group:
        assertions.extend(item.assertions)
        candidates.extend(item.candidates)
    provenance = dict(winner.provenance)
    postprocess = dict(provenance.get("postprocess", {}))
    postprocess["merged_exact_duplicates"] = [entity_payload(item) for item in group if item is not winner]
    provenance["postprocess"] = postprocess
    return replace(
        winner,
        assertions=ordered_valid_assertions(assertions),
        candidates=dedupe_stable(candidates),
        confidence=max(item.confidence for item in group),
        provenance=provenance,
    )


def _mark_overlap_resolution(winner: FinalEntity, reason: str, removed: list[FinalEntity]) -> FinalEntity:
    provenance = dict(winner.provenance)
    postprocess = dict(provenance.get("postprocess", {}))
    previous = list(postprocess.get("resolved_overlaps", []))
    previous.append({"reason": reason, "removed": [entity_payload(item) for item in removed]})
    postprocess["resolved_overlaps"] = previous
    provenance["postprocess"] = postprocess
    return replace(winner, provenance=provenance)


def _same_type_should_resolve(first: FinalEntity, second: FinalEntity, iou_threshold: float) -> bool:
    if str(first.type) in {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}:
        return span_iou(first, second) >= iou_threshold
    return contains(first, second) or contains(second, first) or span_iou(first, second) >= iou_threshold


def _choose_overlap_winner(first: FinalEntity, second: FinalEntity, config: dict[str, Any]) -> tuple[FinalEntity, FinalEntity]:
    first_score = _overlap_score(first, config)
    second_score = _overlap_score(second, config)
    if second_score > first_score:
        return second, first
    return first, second


def _overlap_score(entity: FinalEntity, config: dict[str, Any]) -> tuple[int, float, int, int]:
    text = entity.text.lower()
    slot_score = 0
    if str(entity.type) == "THUỐC":
        parsed = entity.provenance.get("rxnorm_linking", {}).get("parsed", {})
        slot_score += int(bool(parsed.get("strength_value")))
        slot_score += int(bool(parsed.get("route")))
        slot_score += int(bool(parsed.get("frequency")))
    elif str(entity.type) in {"TRIỆU_CHỨNG", "CHẨN_ĐOÁN"}:
        slot_score += int("." not in text and ";" not in text)
    return (slot_score, float(entity.confidence), span_len(entity), -type_priority(str(entity.type), config))


def _different_type_decision(
    first: FinalEntity, second: FinalEntity, config: dict[str, Any]
) -> tuple[FinalEntity, FinalEntity, str] | None:
    iou = span_iou(first, second)
    if not (contains(first, second) or contains(second, first) or iou >= 0.80):
        return None
    for entity, other in ((first, second), (second, first)):
        if str(entity.type) == "KẾT_QUẢ_XÉT_NGHIỆM":
            return entity, other, "lab_result_priority"
        if str(entity.type) == "TÊN_XÉT_NGHIỆM" and entity.provenance.get("chosen_source") in {"lab_rule", "imaging_rule"}:
            return entity, other, "test_name_source_priority"
        if str(entity.type) == "THUỐC" and (entity.candidates or entity.provenance.get("rxnorm_linking")):
            return entity, other, "linked_drug_priority"
    if {str(first.type), str(second.type)} == {"CHẨN_ĐOÁN", "TRIỆU_CHỨNG"}:
        return _diagnosis_symptom_decision(first, second)
    keep, drop = _choose_overlap_winner(first, second, config)
    return keep, drop, "higher_overlap_rank"


def _diagnosis_symptom_decision(first: FinalEntity, second: FinalEntity) -> tuple[FinalEntity, FinalEntity, str]:
    first_features = first.provenance.get("type_features", {})
    second_features = second.provenance.get("type_features", {})
    if str(first.type) == "CHẨN_ĐOÁN" and first_features.get("has_disease_head"):
        return first, second, "diagnosis_disease_head_priority"
    if str(second.type) == "CHẨN_ĐOÁN" and second_features.get("has_disease_head"):
        return second, first, "diagnosis_disease_head_priority"
    if str(first.type) == "TRIỆU_CHỨNG" and first_features.get("has_symptom_head"):
        return first, second, "symptom_head_priority"
    if str(second.type) == "TRIỆU_CHỨNG" and second_features.get("has_symptom_head"):
        return second, first, "symptom_head_priority"
    return (first, second, "higher_confidence") if first.confidence >= second.confidence else (second, first, "higher_confidence")
