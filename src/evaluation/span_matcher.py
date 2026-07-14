from __future__ import annotations

from collections import defaultdict

from src.evaluation.models import EvalEntity, EntityPair


def overlap_len(a: EvalEntity, b: EvalEntity) -> int:
    return max(0, min(a.end, b.end) - max(a.start, b.start))


def span_iou(a: EvalEntity, b: EvalEntity) -> float:
    overlap = overlap_len(a, b)
    if overlap <= 0:
        return 0.0
    union = a.span_len + b.span_len - overlap
    if union <= 0:
        return 0.0
    return overlap / union


def containment_ratio(a: EvalEntity, b: EvalEntity) -> float:
    overlap = overlap_len(a, b)
    if overlap <= 0:
        return 0.0
    denominator = min(a.span_len, b.span_len)
    if denominator <= 0:
        return 0.0
    return overlap / denominator


def exact_match_entities(
    predictions: list[EvalEntity],
    golds: list[EvalEntity],
) -> tuple[list[EntityPair], list[EvalEntity], list[EvalEntity]]:
    gold_by_key: dict[tuple[int, int, str], list[EvalEntity]] = defaultdict(list)
    for gold in golds:
        gold_by_key[gold.exact_key].append(gold)

    pairs: list[EntityPair] = []
    unmatched_pred: list[EvalEntity] = []
    used_gold_ids: set[int] = set()
    for pred in predictions:
        bucket = gold_by_key.get(pred.exact_key, [])
        gold = _pop_first_unused(bucket, used_gold_ids)
        if gold is None:
            unmatched_pred.append(pred)
            continue
        used_gold_ids.add(id(gold))
        pairs.append(EntityPair(pred=pred, gold=gold, match_kind="exact", span_iou=1.0, containment_ratio=1.0))

    unmatched_gold = [gold for gold in golds if id(gold) not in used_gold_ids]
    return pairs, unmatched_pred, unmatched_gold


def relaxed_match_entities(
    predictions: list[EvalEntity],
    golds: list[EvalEntity],
    *,
    iou_threshold: float = 0.50,
    containment_threshold: float = 0.80,
) -> tuple[list[EntityPair], list[EvalEntity], list[EvalEntity]]:
    candidates: list[tuple[tuple[float, float, int, int, int], EntityPair]] = []
    for pred in predictions:
        for gold in golds:
            if pred.type != gold.type:
                continue
            iou = span_iou(pred, gold)
            containment = containment_ratio(pred, gold)
            if iou < iou_threshold and containment < containment_threshold:
                continue
            span_diff = abs(pred.span_len - gold.span_len)
            sort_key = (-iou, -containment, span_diff, pred.index, gold.index)
            candidates.append((sort_key, EntityPair(pred=pred, gold=gold, match_kind="relaxed", span_iou=iou, containment_ratio=containment)))
    candidates.sort(key=lambda item: item[0])

    used_pred_ids: set[int] = set()
    used_gold_ids: set[int] = set()
    pairs: list[EntityPair] = []
    for _, pair in candidates:
        pred_id = id(pair.pred)
        gold_id = id(pair.gold)
        if pred_id in used_pred_ids or gold_id in used_gold_ids:
            continue
        used_pred_ids.add(pred_id)
        used_gold_ids.add(gold_id)
        pairs.append(pair)

    unmatched_pred = [pred for pred in predictions if id(pred) not in used_pred_ids]
    unmatched_gold = [gold for gold in golds if id(gold) not in used_gold_ids]
    return pairs, unmatched_pred, unmatched_gold


def nearest_overlaps(
    predictions: list[EvalEntity],
    golds: list[EvalEntity],
    *,
    min_overlap: int = 1,
) -> list[EntityPair]:
    pairs: list[EntityPair] = []
    for pred in predictions:
        best: EntityPair | None = None
        best_key: tuple[float, float, int] | None = None
        for gold in golds:
            overlap = overlap_len(pred, gold)
            if overlap < min_overlap:
                continue
            iou = span_iou(pred, gold)
            containment = containment_ratio(pred, gold)
            key = (iou, containment, overlap)
            if best_key is None or key > best_key:
                best_key = key
                best = EntityPair(pred=pred, gold=gold, match_kind="nearest_overlap", span_iou=iou, containment_ratio=containment)
        if best is not None:
            pairs.append(best)
    return pairs


def _pop_first_unused(bucket: list[EvalEntity], used_gold_ids: set[int]) -> EvalEntity | None:
    for gold in bucket:
        if id(gold) not in used_gold_ids:
            return gold
    return None