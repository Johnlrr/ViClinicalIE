from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.data_types import VALID_ENTITY_TYPES


@dataclass(slots=True)
class EntityAnnotation:
    text: str
    start: int
    end: int
    type: str
    source: str = ""
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "type": self.type,
        }
        if self.source:
            data["source"] = self.source
        if self.score is not None:
            data["score"] = self.score
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass(slots=True)
class NerExample:
    file_id: str
    text: str
    entities: list[EntityAnnotation]
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "text": self.text,
            "source": self.source,
            "entities": [entity.to_dict() for entity in self.entities],
        }


def records_to_entities(
    records: list[dict[str, Any]],
    raw_text: str,
    *,
    source: str,
    label_types: set[str] | None = None,
    keep_invalid: bool = False,
) -> tuple[list[EntityAnnotation], list[str]]:
    allowed = label_types or set(VALID_ENTITY_TYPES)
    entities: list[EntityAnnotation] = []
    errors: list[str] = []
    for index, record in enumerate(records):
        entity_type = str(record.get("type", ""))
        if entity_type not in allowed:
            continue
        start, end = _record_position(record)
        text = str(record.get("text", ""))
        error = validate_entity_offset(raw_text, text, start, end, file_id="", index=index)
        if error:
            errors.append(error)
            if not keep_invalid:
                continue
        entities.append(
            EntityAnnotation(
                text=raw_text[start:end] if 0 <= start <= end <= len(raw_text) else text,
                start=start,
                end=end,
                type=entity_type,
                source=source,
                score=_optional_float(record.get("score")),
            )
        )
    return select_non_overlapping_entities(entities), errors


def validate_example_offsets(example: NerExample) -> list[str]:
    errors: list[str] = []
    for index, entity in enumerate(example.entities):
        error = validate_entity_offset(example.text, entity.text, entity.start, entity.end, file_id=example.file_id, index=index)
        if error:
            errors.append(error)
    return errors


def validate_entity_offset(raw_text: str, text: str, start: int, end: int, *, file_id: str = "", index: int = 0) -> str | None:
    prefix = f"{file_id}:" if file_id else ""
    if start < 0 or end <= start or end > len(raw_text):
        return f"{prefix}{index}: invalid span {start}:{end} for text length {len(raw_text)}"
    actual = raw_text[start:end]
    if actual != text:
        return f"{prefix}{index}: offset mismatch {start}:{end}; expected={text!r}; actual={actual!r}"
    return None


def select_non_overlapping_entities(entities: list[EntityAnnotation]) -> list[EntityAnnotation]:
    """Keep deterministic non-overlapping labels for token-classification training.

    Priority: earlier start, longer span, higher score, stable type/source text. This prevents
    inconsistent BIO labels when Phase 9 predictions contain nested/overlapping mentions.
    """
    sorted_entities = sorted(
        entities,
        key=lambda item: (item.start, -(item.end - item.start), -(item.score or 0.0), item.type, item.source),
    )
    selected: list[EntityAnnotation] = []
    cursor = -1
    for entity in sorted_entities:
        if entity.start < cursor:
            continue
        selected.append(entity)
        cursor = entity.end
    return selected


def entities_to_char_bio(raw_text: str, entities: list[EntityAnnotation]) -> list[str]:
    labels = ["O"] * len(raw_text)
    for entity in select_non_overlapping_entities(entities):
        if entity.start < 0 or entity.end > len(raw_text) or entity.end <= entity.start:
            continue
        labels[entity.start] = f"B-{entity.type}"
        for index in range(entity.start + 1, entity.end):
            labels[index] = f"I-{entity.type}"
    return labels


def char_bio_to_entities(raw_text: str, labels: list[str], *, source: str = "bio") -> list[EntityAnnotation]:
    entities: list[EntityAnnotation] = []
    start: int | None = None
    active_type: str | None = None
    for index, label in enumerate(labels + ["O"]):
        prefix, entity_type = _split_bio(label)
        if prefix == "B" or prefix == "O" or entity_type != active_type:
            if start is not None and active_type is not None:
                entities.append(EntityAnnotation(raw_text[start:index], start, index, active_type, source=source))
            start = index if prefix in {"B", "I"} and entity_type else None
            active_type = entity_type if prefix in {"B", "I"} else None
        elif prefix == "I" and start is None and entity_type:
            start = index
            active_type = entity_type
    return entities


def labels_for_entity_types(entity_types: list[str]) -> list[str]:
    labels = ["O"]
    for entity_type in entity_types:
        labels.extend([f"B-{entity_type}", f"I-{entity_type}"])
    return labels


def _record_position(record: dict[str, Any]) -> tuple[int, int]:
    position = record.get("position", [0, 0])
    if not isinstance(position, list | tuple) or len(position) < 2:
        return 0, 0
    try:
        return int(position[0]), int(position[1])
    except (TypeError, ValueError):
        return 0, 0


def _split_bio(label: str) -> tuple[str, str | None]:
    if label == "O" or not label:
        return "O", None
    if "-" not in label:
        return "O", None
    prefix, entity_type = label.split("-", 1)
    return prefix, entity_type if entity_type in VALID_ENTITY_TYPES else None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
