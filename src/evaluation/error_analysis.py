from __future__ import annotations

from typing import Any

from src.evaluation.models import EvalEntity, EntityPair
from src.evaluation.span_matcher import containment_ratio, nearest_overlaps, span_iou


def span_mismatch_subtype(pred: EvalEntity, gold: EvalEntity) -> str:
    if pred.start <= gold.start and pred.end >= gold.end:
        return "pred_too_long"
    if gold.start <= pred.start and gold.end >= pred.end:
        return "pred_too_short"
    return "partial_overlap"


def find_span_mismatches(
    unmatched_pred: list[EvalEntity],
    unmatched_gold: list[EvalEntity],
    *,
    iou_threshold: float,
    containment_threshold: float,
    raw_text: str | None = None,
    context_window: int = 120,
) -> list[dict[str, Any]]:
    pairs: list[tuple[tuple[float, float, int, int], EntityPair]] = []
    for pred in unmatched_pred:
        for gold in unmatched_gold:
            if pred.type != gold.type:
                continue
            iou = span_iou(pred, gold)
            containment = containment_ratio(pred, gold)
            if iou < iou_threshold and containment < containment_threshold:
                continue
            pairs.append(((-iou, -containment, pred.index, gold.index), EntityPair(pred, gold, "span_mismatch", iou, containment)))
    return _greedy_diagnostic_records(pairs, "span_mismatch", raw_text, context_window)


def find_type_mismatches(
    unmatched_pred: list[EvalEntity],
    unmatched_gold: list[EvalEntity],
    *,
    iou_threshold: float,
    containment_threshold: float,
    raw_text: str | None = None,
    context_window: int = 120,
) -> list[dict[str, Any]]:
    pairs: list[tuple[tuple[float, float, int, int], EntityPair]] = []
    for pred in unmatched_pred:
        for gold in unmatched_gold:
            if pred.type == gold.type:
                continue
            iou = span_iou(pred, gold)
            containment = containment_ratio(pred, gold)
            if iou < iou_threshold and containment < containment_threshold:
                continue
            pairs.append(((-iou, -containment, pred.index, gold.index), EntityPair(pred, gold, "type_mismatch", iou, containment)))
    return _greedy_diagnostic_records(pairs, "type_mismatch", raw_text, context_window)


def false_positive_records(
    false_positives: list[EvalEntity],
    golds: list[EvalEntity],
    *,
    raw_text: str | None = None,
    context_window: int = 120,
) -> list[dict[str, Any]]:
    nearest = {id(pair.pred): pair for pair in nearest_overlaps(false_positives, golds)}
    records: list[dict[str, Any]] = []
    for pred in false_positives:
        pair = nearest.get(id(pred))
        record: dict[str, Any] = {
            "file_id": pred.file_id,
            "category": "false_positive",
            "pred": pred.to_dict(),
        }
        if pair is not None:
            record.update({"nearest_gold": pair.gold.to_dict(), "span_iou": pair.span_iou, "containment_ratio": pair.containment_ratio})
        if raw_text is not None:
            record["context"] = context_slice(raw_text, pred.start, pred.end, context_window)
        records.append(record)
    return records


def false_negative_records(
    false_negatives: list[EvalEntity],
    predictions: list[EvalEntity],
    *,
    raw_text: str | None = None,
    context_window: int = 120,
) -> list[dict[str, Any]]:
    nearest = {id(pair.gold): pair for pair in nearest_overlaps(predictions, false_negatives)}
    records: list[dict[str, Any]] = []
    for gold in false_negatives:
        pair = nearest.get(id(gold))
        record: dict[str, Any] = {
            "file_id": gold.file_id,
            "category": "false_negative",
            "gold": gold.to_dict(),
        }
        if pair is not None:
            record.update({"nearest_pred": pair.pred.to_dict(), "span_iou": pair.span_iou, "containment_ratio": pair.containment_ratio})
        if raw_text is not None:
            record["context"] = context_slice(raw_text, gold.start, gold.end, context_window)
        records.append(record)
    return records


def pair_record(pair: EntityPair, category: str, *, raw_text: str | None = None, context_window: int = 120) -> dict[str, Any]:
    record = pair.to_dict()
    record["category"] = category
    if category == "span_mismatch":
        record["subcategory"] = span_mismatch_subtype(pair.pred, pair.gold)
    elif category == "type_mismatch":
        record["subcategory"] = f"{pair.pred.type}__vs__{pair.gold.type}"
    if raw_text is not None:
        start = min(pair.pred.start, pair.gold.start)
        end = max(pair.pred.end, pair.gold.end)
        record["context"] = context_slice(raw_text, start, end, context_window)
    return record


def context_slice(raw_text: str, start: int, end: int, window: int = 120) -> dict[str, Any]:
    context_start = max(0, start - window)
    context_end = min(len(raw_text), end + window)
    return {
        "start": context_start,
        "end": context_end,
        "entity_start": start,
        "entity_end": end,
        "text": raw_text[context_start:context_end],
    }


def _greedy_diagnostic_records(
    candidates: list[tuple[tuple[float, float, int, int], EntityPair]],
    category: str,
    raw_text: str | None,
    context_window: int,
) -> list[dict[str, Any]]:
    candidates.sort(key=lambda item: item[0])
    used_pred_ids: set[int] = set()
    used_gold_ids: set[int] = set()
    records: list[dict[str, Any]] = []
    for _, pair in candidates:
        pred_id = id(pair.pred)
        gold_id = id(pair.gold)
        if pred_id in used_pred_ids or gold_id in used_gold_ids:
            continue
        used_pred_ids.add(pred_id)
        used_gold_ids.add(gold_id)
        records.append(pair_record(pair, category, raw_text=raw_text, context_window=context_window))
    return records