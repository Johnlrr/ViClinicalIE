from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from src.data_types import Chunk, SpanCandidate, TextViews


@dataclass(slots=True)
class ExtractionContext:
    raw_text: str
    views: TextViews
    chunks: list[Chunk]
    resources: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


class BaseExtractor(ABC):
    name: str = "base"

    @abstractmethod
    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        raise NotImplementedError
