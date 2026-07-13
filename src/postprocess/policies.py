from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.data_types import FinalEntity, VALID_ASSERTIONS


ASSERTABLE_TYPES = {"TRIỆU_CHỨNG", "CHẨN_ĐOÁN", "THUỐC"}
LINKED_TYPES = {"CHẨN_ĐOÁN", "THUỐC"}
ASSERTION_ORDER = ["isNegated", "isFamily", "isHistorical"]
DEFAULT_TYPE_PRIORITY = {
    "TÊN_XÉT_NGHIỆM": 10,
    "KẾT_QUẢ_XÉT_NGHIỆM": 20,
    "THUỐC": 30,
    "CHẨN_ĐOÁN": 40,
    "TRIỆU_CHỨNG": 50,
}


def type_priority(entity_type: str, config: Mapping[str, Any] | None = None) -> int:
    cfg = config or {}
    priority = dict(DEFAULT_TYPE_PRIORITY)
    sorting_cfg = cfg.get("sorting", {}) if isinstance(cfg.get("sorting"), dict) else {}
    priority.update(dict(sorting_cfg.get("type_priority", {})))
    return int(priority.get(str(entity_type), 999))


def is_assertable(entity: FinalEntity) -> bool:
    return str(entity.type) in ASSERTABLE_TYPES


def is_linked_type(entity: FinalEntity) -> bool:
    return str(entity.type) in LINKED_TYPES


def source_priority(entity: FinalEntity) -> int:
    value = entity.provenance.get("source_priority", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def entity_rank(entity: FinalEntity, config: Mapping[str, Any] | None = None) -> tuple[float, int, int, int]:
    return (
        float(entity.confidence),
        source_priority(entity),
        len(entity.candidates),
        -type_priority(str(entity.type), config),
    )


def dedupe_stable(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def ordered_valid_assertions(assertions: list[str]) -> list[str]:
    present = {item for item in assertions if item in VALID_ASSERTIONS}
    return [item for item in ASSERTION_ORDER if item in present]
