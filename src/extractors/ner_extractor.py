from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.data_types import SpanCandidate
from src.extractors.base import BaseExtractor, ExtractionContext


class NERExtractor(BaseExtractor):
    name = "ner"

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        return []
