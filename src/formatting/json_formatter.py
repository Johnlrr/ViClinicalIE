from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.data_types import FinalEntity
from src.io_utils import write_json
from src.postprocess.policies import ASSERTION_ORDER, LINKED_TYPES, dedupe_stable


def format_entity(entity: FinalEntity, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or {})
    include_assertions = bool(cfg.get("include_assertions_for_all_types", True))
    include_candidates = bool(cfg.get("include_candidates_for_linked_types", True))
    include_empty_candidates = bool(cfg.get("include_empty_candidates_for_linked_types", True))

    entity_type = str(entity.type)
    record: dict[str, Any] = {
        "text": entity.text,
        "position": [int(entity.start), int(entity.end)],
        "type": entity_type,
    }
    if include_assertions:
        record["assertions"] = _dedupe_assertions_preserve_invalid(list(entity.assertions))
    if include_candidates and entity_type in LINKED_TYPES:
        candidates = dedupe_stable(list(entity.candidates))
        if candidates or include_empty_candidates:
            record["candidates"] = candidates
    return record


def format_entities(entities: list[FinalEntity], config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    return [format_entity(entity, config) for entity in entities]


def write_prediction_json(
    records: list[dict[str, Any]],
    output_path: str | Path,
    config: Mapping[str, Any] | None = None,
) -> None:
    cfg = dict(config or {})
    indent = int(cfg.get("indent", 2))
    write_json(output_path, records, indent=indent)


class PredictionFormatter:
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def format_entity(self, entity: FinalEntity) -> dict[str, Any]:
        return format_entity(entity, self.config)

    def format_entities(self, entities: list[FinalEntity]) -> list[dict[str, Any]]:
        return format_entities(entities, self.config)

    def write(self, entities: list[FinalEntity], output_path: str | Path) -> list[dict[str, Any]]:
        records = self.format_entities(entities)
        write_prediction_json(records, output_path, self.config)
        return records


def _dedupe_assertions_preserve_invalid(assertions: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for assertion in ASSERTION_ORDER:
        if assertion in assertions and assertion not in seen:
            ordered.append(assertion)
            seen.add(assertion)
    for assertion in assertions:
        if assertion in seen:
            continue
        ordered.append(assertion)
        seen.add(assertion)
    return ordered