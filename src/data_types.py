from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EntityType = Literal[
    "TRIỆU_CHỨNG",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
    "CHẨN_ĐOÁN",
    "THUỐC",
]

Terminology = Literal["ICD10", "RXNORM"]

VALID_ENTITY_TYPES: set[str] = {
    "TRIỆU_CHỨNG",
    "TÊN_XÉT_NGHIỆM",
    "KẾT_QUẢ_XÉT_NGHIỆM",
    "CHẨN_ĐOÁN",
    "THUỐC",
}

VALID_ASSERTIONS: set[str] = {
    "isNegated",
    "isFamily",
    "isHistorical",
}


@dataclass(slots=True)
class SpanCandidate:
    text: str
    start: int
    end: int
    raw_type: str | None
    source: str
    score: float
    section: str | None = None
    subsection: str | None = None
    context_left: str = ""
    context_right: str = ""
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FinalEntity:
    text: str
    start: int
    end: int
    type: EntityType | str
    assertions: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def position(self) -> list[int]:
        return [self.start, self.end]


@dataclass(slots=True)
class MappingCandidate:
    code: str
    name: str
    terminology: Terminology
    lexical_score: float = 0.0
    dense_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

