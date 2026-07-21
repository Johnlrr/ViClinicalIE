from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.io_utils import read_json
from src.postprocess.policies import ASSERTABLE_TYPES, LINKED_TYPES


SCORER_PROFILE = "official_like_v1"
WEIGHTS = {"text": 0.3, "assertions": 0.3, "candidates": 0.4}


@dataclass(slots=True)
class RecordScore:
    file_id: str
    text: float
    assertions: float
    candidates: float
    candidate_weight: int
    pred_count: int
    gold_count: int


@dataclass(slots=True)
class OfficialLikeScore:
    text_score: float
    assertions_score: float
    candidates_score: float
    final_score: float
    records: list[RecordScore] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorer_profile": SCORER_PROFILE,
            "official": False,
            "assumptions": {
                "matching": "greedy maximum character overlap with identical entity type",
                "text": "mean per-document 1-WER over position-ordered concatenated entity texts",
                "attributes": "whole-document Jaccard keyed by matched concept identity",
                "candidate_weight": "sum over gold linked entities of len(candidates)+1",
            },
            "text_score": self.text_score,
            "assertions_score": self.assertions_score,
            "candidates_score": self.candidates_score,
            "final_score": self.final_score,
            "records": [asdict(record) for record in self.records],
        }


def score_directories(pred_dir: str | Path, gold_dir: str | Path, *, ids: Iterable[str] | None = None) -> OfficialLikeScore:
    gold_path = Path(gold_dir)
    pred_path = Path(pred_dir)
    stems = list(ids) if ids is not None else [path.stem for path in sorted(gold_path.glob("*.json"), key=lambda item: _natural_key(item.stem))]
    golds = {stem: read_json(gold_path / f"{stem}.json") for stem in stems}
    preds = {stem: read_json(pred_path / f"{stem}.json") if (pred_path / f"{stem}.json").is_file() else [] for stem in stems}
    return score_corpus(preds, golds, stems=stems)


def score_corpus(
    predictions: Mapping[str, Sequence[dict[str, Any]]],
    golds: Mapping[str, Sequence[dict[str, Any]]],
    *,
    stems: Sequence[str] | None = None,
) -> OfficialLikeScore:
    selected = list(stems) if stems is not None else sorted(golds, key=_natural_key)
    records = [score_record(stem, predictions.get(stem, ()), golds[stem]) for stem in selected]
    count = len(records) or 1
    text = sum(record.text for record in records) / count
    assertions = sum(record.assertions for record in records) / count
    weight = sum(record.candidate_weight for record in records)
    candidates = sum(record.candidates * record.candidate_weight for record in records) / weight if weight else 1.0
    final = WEIGHTS["text"] * text + WEIGHTS["assertions"] * assertions + WEIGHTS["candidates"] * candidates
    return OfficialLikeScore(text, assertions, candidates, final, records)


def score_record(file_id: str, pred: Sequence[dict[str, Any]], gold: Sequence[dict[str, Any]]) -> RecordScore:
    matched = match_concepts(pred, gold)
    pred_ids = {index: ("g", matched[index]) if index in matched else ("p", index) for index in range(len(pred))}
    gold_ids = {index: ("g", index) for index in range(len(gold))}
    pred_assertions = _attribute_set(pred, pred_ids, "assertions", ASSERTABLE_TYPES)
    gold_assertions = _attribute_set(gold, gold_ids, "assertions", ASSERTABLE_TYPES)
    pred_candidates = _attribute_set(pred, pred_ids, "candidates", LINKED_TYPES)
    gold_candidates = _attribute_set(gold, gold_ids, "candidates", LINKED_TYPES)
    candidate_weight = sum(len(record.get("candidates", []) or []) + 1 for record in gold if record.get("type") in LINKED_TYPES)
    return RecordScore(
        file_id=file_id,
        text=_text_score(pred, gold),
        assertions=_jaccard(pred_assertions, gold_assertions),
        candidates=_jaccard(pred_candidates, gold_candidates),
        candidate_weight=candidate_weight,
        pred_count=len(pred),
        gold_count=len(gold),
    )


def match_concepts(pred: Sequence[dict[str, Any]], gold: Sequence[dict[str, Any]]) -> dict[int, int]:
    pairs: list[tuple[int, int, int]] = []
    for pred_index, pred_record in enumerate(pred):
        for gold_index, gold_record in enumerate(gold):
            if pred_record.get("type") != gold_record.get("type"):
                continue
            overlap = _overlap(_span(pred_record), _span(gold_record))
            if overlap:
                pairs.append((-overlap, pred_index, gold_index))
    matched: dict[int, int] = {}
    used_gold: set[int] = set()
    for _, pred_index, gold_index in sorted(pairs):
        if pred_index in matched or gold_index in used_gold:
            continue
        matched[pred_index] = gold_index
        used_gold.add(gold_index)
    return matched


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    previous = list(range(len(hypothesis_words) + 1))
    for row, reference_word in enumerate(reference_words, start=1):
        current = [row]
        for column, hypothesis_word in enumerate(hypothesis_words, start=1):
            substitution = previous[column - 1] + (reference_word != hypothesis_word)
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1] / len(reference_words)


def _text_score(pred: Sequence[dict[str, Any]], gold: Sequence[dict[str, Any]]) -> float:
    reference = _concat_text(gold)
    hypothesis = _concat_text(pred)
    return max(0.0, min(1.0, 1.0 - word_error_rate(reference, hypothesis)))


def _concat_text(records: Sequence[dict[str, Any]]) -> str:
    ordered = sorted(records, key=lambda record: tuple(record.get("position", (0, 0))))
    return " ".join(str(record.get("text", "")) for record in ordered).strip()


def _attribute_set(records: Sequence[dict[str, Any]], concept_ids: Mapping[int, tuple[str, int]], field: str, valid_types: set[str]) -> set[tuple[tuple[str, int], str]]:
    return {
        (concept_ids[index], str(value))
        for index, record in enumerate(records)
        if record.get("type") in valid_types
        for value in record.get(field, []) or []
    }


def _jaccard(first: set[Any], second: set[Any]) -> float:
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _span(record: Mapping[str, Any]) -> tuple[int, int]:
    start, end = record["position"]
    return int(start), int(end)


def _overlap(first: tuple[int, int], second: tuple[int, int]) -> int:
    return max(0, min(first[1], second[1]) - max(first[0], second[0]))


def _natural_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)