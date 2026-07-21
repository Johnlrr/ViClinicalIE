from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from src.data_types import VALID_ASSERTIONS, VALID_ENTITY_TYPES
from src.evaluation.models import EvalEntity, EntityPair, EvaluationFileResult, PRFCounts
from src.postprocess.policies import ASSERTABLE_TYPES, LINKED_TYPES


def counts_from_match_result(
    matched: list[EntityPair],
    unmatched_pred: list[EvalEntity],
    unmatched_gold: list[EvalEntity],
) -> PRFCounts:
    return PRFCounts(tp=len(matched), fp=len(unmatched_pred), fn=len(unmatched_gold))


def aggregate_counts(file_results: list[EvaluationFileResult], attr: str) -> PRFCounts:
    total = PRFCounts()
    for result in file_results:
        total.add(getattr(result, attr))
    return total


def counts_by_type(
    predictions: list[EvalEntity],
    golds: list[EvalEntity],
    pairs: list[EntityPair],
) -> dict[str, PRFCounts]:
    counts: dict[str, PRFCounts] = {entity_type: PRFCounts() for entity_type in sorted(VALID_ENTITY_TYPES)}
    # Directory evaluation reconstructs entities after per-file matching, so
    # Python object identity is not stable. File ID + record index is stable.
    matched_pred_ids = {(pair.pred.file_id, pair.pred.index) for pair in pairs}
    matched_gold_ids = {(pair.gold.file_id, pair.gold.index) for pair in pairs}
    for pair in pairs:
        counts.setdefault(pair.gold.type, PRFCounts()).tp += 1
    for pred in predictions:
        if (pred.file_id, pred.index) not in matched_pred_ids:
            counts.setdefault(pred.type, PRFCounts()).fp += 1
    for gold in golds:
        if (gold.file_id, gold.index) not in matched_gold_ids:
            counts.setdefault(gold.type, PRFCounts()).fn += 1
    return {key: value for key, value in counts.items() if value.tp or value.fp or value.fn}


def aggregate_type_counts(type_counts_by_file: list[dict[str, PRFCounts]]) -> dict[str, PRFCounts]:
    total: dict[str, PRFCounts] = defaultdict(PRFCounts)
    for by_type in type_counts_by_file:
        for entity_type, counts in by_type.items():
            total[entity_type].add(counts)
    return dict(total)


def compute_assertion_metrics(pairs: list[EntityPair]) -> dict[str, Any]:
    label_counts = {label: PRFCounts() for label in sorted(VALID_ASSERTIONS)}
    total_assertable = 0
    exact_set_matches = 0
    mismatches: list[dict[str, Any]] = []
    for pair in pairs:
        if pair.gold.type not in ASSERTABLE_TYPES:
            continue
        total_assertable += 1
        pred_set = set(pair.pred.assertions)
        gold_set = set(pair.gold.assertions)
        if pred_set == gold_set:
            exact_set_matches += 1
        else:
            mismatches.append(
                {
                    "file_id": pair.gold.file_id,
                    "category": "assertion_mismatch",
                    "pred": pair.pred.to_dict(),
                    "gold": pair.gold.to_dict(),
                    "missing_assertions": sorted(gold_set - pred_set),
                    "extra_assertions": sorted(pred_set - gold_set),
                }
            )
        for label in sorted(VALID_ASSERTIONS):
            in_pred = label in pred_set
            in_gold = label in gold_set
            if in_pred and in_gold:
                label_counts[label].tp += 1
            elif in_pred and not in_gold:
                label_counts[label].fp += 1
            elif not in_pred and in_gold:
                label_counts[label].fn += 1
    return {
        "total_matched_assertable": total_assertable,
        "exact_set_match_count": exact_set_matches,
        "exact_set_match_rate": round(exact_set_matches / total_assertable, 6) if total_assertable else 0.0,
        "by_label": {label: counts.to_dict() for label, counts in sorted(label_counts.items())},
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def compute_candidate_metrics(pairs: list[EntityPair], *, skip_empty_gold_candidates: bool = True) -> dict[str, Any]:
    by_type = {entity_type: _empty_candidate_type_metrics() for entity_type in sorted(LINKED_TYPES)}
    total_evaluable = 0
    hit_count = 0
    exact_set_match_count = 0
    skipped_empty_gold = 0
    mismatch_counts: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    for pair in pairs:
        if pair.gold.type not in LINKED_TYPES:
            continue
        pred_set = set(pair.pred.candidates)
        gold_set = set(pair.gold.candidates)
        if not gold_set and skip_empty_gold_candidates:
            skipped_empty_gold += 1
            by_type[pair.gold.type]["skipped_empty_gold"] += 1
            continue
        total_evaluable += 1
        by_type[pair.gold.type]["total_evaluable"] += 1
        hit = bool(pred_set & gold_set) if gold_set else pred_set == gold_set
        exact = pred_set == gold_set
        if hit:
            hit_count += 1
            by_type[pair.gold.type]["hit_count"] += 1
        if exact:
            exact_set_match_count += 1
            by_type[pair.gold.type]["exact_set_match_count"] += 1

        category = _candidate_mismatch_category(pred_set, gold_set)
        mismatch_counts[category] += 1
        if category != "exact_candidate_match":
            record = {
                "file_id": pair.gold.file_id,
                "category": "candidate_mismatch",
                "subcategory": category,
                "pred": pair.pred.to_dict(),
                "gold": pair.gold.to_dict(),
                "missing_candidates": sorted(gold_set - pred_set),
                "extra_candidates": sorted(pred_set - gold_set),
                "intersection": sorted(pred_set & gold_set),
            }
            mismatches.append(record)
    for metrics in by_type.values():
        total = metrics["total_evaluable"]
        metrics["hit_rate"] = round(metrics["hit_count"] / total, 6) if total else 0.0
        metrics["exact_set_match_rate"] = round(metrics["exact_set_match_count"] / total, 6) if total else 0.0
    return {
        "total_evaluable": total_evaluable,
        "hit_count": hit_count,
        "hit_rate": round(hit_count / total_evaluable, 6) if total_evaluable else 0.0,
        "exact_set_match_count": exact_set_match_count,
        "exact_set_match_rate": round(exact_set_match_count / total_evaluable, 6) if total_evaluable else 0.0,
        "skipped_empty_gold": skipped_empty_gold,
        "mismatch_counts": dict(sorted(mismatch_counts.items())),
        "by_type": by_type,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _empty_candidate_type_metrics() -> dict[str, Any]:
    return {
        "total_evaluable": 0,
        "hit_count": 0,
        "hit_rate": 0.0,
        "exact_set_match_count": 0,
        "exact_set_match_rate": 0.0,
        "skipped_empty_gold": 0,
    }


def _candidate_mismatch_category(pred_set: set[str], gold_set: set[str]) -> str:
    if pred_set == gold_set:
        return "exact_candidate_match"
    if not pred_set and gold_set:
        return "missing_candidate"
    if pred_set and not gold_set:
        return "extra_candidate_when_gold_empty"
    if pred_set & gold_set:
        return "partial_candidate"
    return "wrong_candidate"