from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.data_types import SpanCandidate, VALID_ENTITY_TYPES


@dataclass(slots=True)
class NerTokenPrediction:
    start: int
    end: int
    label: str
    score: float


def decode_token_predictions(
    raw_text: str,
    predictions: list[NerTokenPrediction],
    *,
    threshold_by_type: dict[str, float] | None = None,
    max_entity_chars: dict[str, int] | None = None,
    default_threshold: float = 0.85,
    source: str = "ner",
    section: str | None = None,
    subsection: str | None = None,
) -> list[SpanCandidate]:
    threshold_by_type = threshold_by_type or {}
    max_entity_chars = max_entity_chars or {}
    spans: list[SpanCandidate] = []
    active_start: int | None = None
    active_end: int | None = None
    active_type: str | None = None
    active_scores: list[float] = []

    for prediction in sorted(predictions, key=lambda item: (item.start, item.end)) + [NerTokenPrediction(len(raw_text), len(raw_text), "O", 1.0)]:
        prefix, entity_type = split_bio_label(prediction.label)
        starts_new = prefix == "B" or prefix == "O" or entity_type != active_type or (active_end is not None and prediction.start > active_end + 1)
        if starts_new and active_start is not None and active_end is not None and active_type is not None:
            candidate = _candidate_from_active(
                raw_text,
                active_start,
                active_end,
                active_type,
                active_scores,
                threshold_by_type=threshold_by_type,
                max_entity_chars=max_entity_chars,
                default_threshold=default_threshold,
                source=source,
                section=section,
                subsection=subsection,
            )
            if candidate is not None:
                spans.append(candidate)
            active_start = None
            active_end = None
            active_type = None
            active_scores = []

        if prefix in {"B", "I"} and entity_type:
            if active_start is None:
                active_start = prediction.start
                active_type = entity_type
            active_end = prediction.end
            active_scores.append(float(prediction.score))

    return spans


def split_bio_label(label: str) -> tuple[str, str | None]:
    if not label or label == "O" or "-" not in label:
        return "O", None
    prefix, entity_type = label.split("-", 1)
    if prefix not in {"B", "I"} or entity_type not in VALID_ENTITY_TYPES:
        return "O", None
    return prefix, entity_type


def _candidate_from_active(
    raw_text: str,
    start: int,
    end: int,
    entity_type: str,
    scores: list[float],
    *,
    threshold_by_type: dict[str, float],
    max_entity_chars: dict[str, int],
    default_threshold: float,
    source: str,
    section: str | None,
    subsection: str | None,
) -> SpanCandidate | None:
    if start < 0 or end <= start or end > len(raw_text):
        return None
    score = sum(scores) / len(scores) if scores else 0.0
    threshold = float(threshold_by_type.get(entity_type, default_threshold))
    if score < threshold:
        return None
    trimmed_start, trimmed_end = _trim_span(raw_text, start, end)
    if trimmed_end <= trimmed_start:
        return None
    if max_entity_chars.get(entity_type) and trimmed_end - trimmed_start > int(max_entity_chars[entity_type]):
        return None
    text = raw_text[trimmed_start:trimmed_end]
    if _bad_span_text(text):
        return None
    return SpanCandidate(
        text=text,
        start=trimmed_start,
        end=trimmed_end,
        raw_type=entity_type,
        source=source,
        score=score,
        section=section,
        subsection=subsection,
        context_left=raw_text[max(0, trimmed_start - 120) : trimmed_start],
        context_right=raw_text[trimmed_end : min(len(raw_text), trimmed_end + 120)],
        features={
            "ner_label": entity_type,
            "ner_score": score,
            "source_priority": -1,
            "rule": "ner_model",
        },
    )


def _trim_span(raw_text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    return start, end


def _bad_span_text(text: str) -> bool:
    stripped = text.strip(" \t\r\n-–—,;:.()[]{}")
    if not stripped:
        return True
    if text.count("\n") >= 2:
        return True
    return False


def token_predictions_from_dicts(rows: list[dict[str, Any]]) -> list[NerTokenPrediction]:
    predictions: list[NerTokenPrediction] = []
    for row in rows:
        predictions.append(
            NerTokenPrediction(
                start=int(row.get("start", 0)),
                end=int(row.get("end", 0)),
                label=str(row.get("label", "O")),
                score=float(row.get("score", 0.0)),
            )
        )
    return predictions
