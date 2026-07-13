from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.data_types import FinalEntity


def entity_key(entity: FinalEntity) -> tuple[int, int, str]:
    return (int(entity.start), int(entity.end), str(entity.type))


def entity_payload(entity: FinalEntity) -> dict[str, Any]:
    return {
        "text": entity.text,
        "type": str(entity.type),
        "position": [entity.start, entity.end],
        "assertions": list(entity.assertions),
        "candidates": list(entity.candidates),
        "confidence": entity.confidence,
        "chosen_source": entity.provenance.get("chosen_source"),
        "type_resolution_reason": entity.provenance.get("type_resolution_reason"),
    }


def span_len(entity: FinalEntity) -> int:
    return max(0, int(entity.end) - int(entity.start))


def overlap_len(first: FinalEntity, second: FinalEntity) -> int:
    return max(0, min(first.end, second.end) - max(first.start, second.start))


def overlaps(first: FinalEntity, second: FinalEntity) -> bool:
    return overlap_len(first, second) > 0


def contains(container: FinalEntity, contained: FinalEntity) -> bool:
    return container.start <= contained.start and container.end >= contained.end


def same_span(first: FinalEntity, second: FinalEntity) -> bool:
    return first.start == second.start and first.end == second.end


def span_iou(first: FinalEntity, second: FinalEntity) -> float:
    intersection = overlap_len(first, second)
    if intersection <= 0:
        return 0.0
    union = span_len(first) + span_len(second) - intersection
    return intersection / union if union > 0 else 0.0


def validate_entity_offset(entity: FinalEntity, raw_text: str) -> str | None:
    if entity.start < 0 or entity.end > len(raw_text) or entity.start >= entity.end:
        return f"invalid_span:{entity.start}-{entity.end}:{entity.type}:{entity.text!r}"
    if raw_text[entity.start : entity.end] != entity.text:
        return f"offset_mismatch:{entity.start}-{entity.end}:{entity.type}:{entity.text!r}"
    return None


def with_span(entity: FinalEntity, raw_text: str, start: int, end: int) -> FinalEntity:
    if start < 0 or end > len(raw_text) or start >= end:
        raise ValueError(f"Invalid replacement span: {start}-{end}")
    return replace(entity, start=start, end=end, text=raw_text[start:end])
