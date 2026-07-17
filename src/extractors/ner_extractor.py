from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.data_types import SpanCandidate
from src.extractors.base import BaseExtractor, ExtractionContext
from src.ner.model_inference import NerModelRunner
from src.ner.span_decoder import NerTokenPrediction, decode_token_predictions, token_predictions_from_dicts


class NERExtractor(BaseExtractor):
    name = "ner"

    def __init__(self, *, config: Mapping[str, Any] | None = None, model_runner: NerModelRunner | None = None) -> None:
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        self.model_dir = self.config.get("model_dir")
        self.device = int(self.config.get("device", -1))
        self.threshold_by_type = {str(key): float(value) for key, value in dict(self.config.get("threshold", {})).items()}
        self.max_entity_chars = {str(key): int(value) for key, value in dict(self.config.get("max_entity_chars", {})).items()}
        self.default_threshold = float(self.config.get("default_threshold", 0.85))
        self.model_runner = model_runner if model_runner is not None else NerModelRunner(self.model_dir, device=self.device)

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        if not self.enabled:
            return []
        if self.config.get("mock_token_predictions"):
            return self._extract_from_mock_predictions(context)
        if not self.model_runner.available:
            return []

        candidates: list[SpanCandidate] = []
        chunks = context.chunks or []
        if not chunks:
            predictions = self.model_runner.predict(context.raw_text)
            return decode_token_predictions(
                context.raw_text,
                predictions,
                threshold_by_type=self.threshold_by_type,
                max_entity_chars=self.max_entity_chars,
                default_threshold=self.default_threshold,
                source="ner",
            )

        for chunk in chunks:
            local_predictions = self.model_runner.predict(chunk.text)
            shifted = [
                NerTokenPrediction(
                    start=chunk.start + prediction.start,
                    end=chunk.start + prediction.end,
                    label=prediction.label,
                    score=prediction.score,
                )
                for prediction in local_predictions
            ]
            candidates.extend(
                decode_token_predictions(
                    context.raw_text,
                    shifted,
                    threshold_by_type=self.threshold_by_type,
                    max_entity_chars=self.max_entity_chars,
                    default_threshold=self.default_threshold,
                    source="ner",
                    section=chunk.section,
                    subsection=chunk.subsection,
                )
            )
        return _dedupe_candidates(candidates)

    def _extract_from_mock_predictions(self, context: ExtractionContext) -> list[SpanCandidate]:
        predictions = token_predictions_from_dicts(list(self.config.get("mock_token_predictions", [])))
        return decode_token_predictions(
            context.raw_text,
            predictions,
            threshold_by_type=self.threshold_by_type,
            max_entity_chars=self.max_entity_chars,
            default_threshold=self.default_threshold,
            source="ner",
        )


def _dedupe_candidates(candidates: list[SpanCandidate]) -> list[SpanCandidate]:
    seen: set[tuple[int, int, str | None]] = set()
    output: list[SpanCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, item.end, item.raw_type or "", -item.score)):
        key = (candidate.start, candidate.end, candidate.raw_type)
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output
