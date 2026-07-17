from __future__ import annotations

from pathlib import Path
from typing import Any

from src.ner.span_decoder import NerTokenPrediction


class NerModelRunner:
    """Optional HuggingFace token-classification runner.

    Phase 14 intentionally does not train or require a model. If `model_dir` is missing or
    transformers/torch are unavailable, the runner stays unavailable and returns no predictions.
    """

    def __init__(self, model_dir: str | Path | None = None, *, device: int = -1) -> None:
        self.model_dir = Path(model_dir) if model_dir else None
        self.device = device
        self.available = False
        self.error: str | None = None
        self._pipeline: Any = None
        if self.model_dir is not None:
            self._try_load()

    def predict(self, text: str) -> list[NerTokenPrediction]:
        if not self.available or self._pipeline is None or not text:
            return []
        try:
            outputs = self._pipeline(text)
        except Exception as exc:  # pragma: no cover - depends on optional external model runtime
            self.error = f"NER inference failed: {exc}"
            return []
        return self._outputs_to_predictions(outputs)

    def _try_load(self) -> None:
        if self.model_dir is None or not self.model_dir.exists():
            self.error = f"NER model_dir does not exist: {self.model_dir}"
            return
        try:
            from transformers import pipeline  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency path
            self.error = f"transformers is not available: {exc}"
            return
        try:
            self._pipeline = pipeline(
                "token-classification",
                model=str(self.model_dir),
                tokenizer=str(self.model_dir),
                aggregation_strategy="none",
                device=self.device,
            )
            self.available = True
            self.error = None
        except Exception as exc:  # pragma: no cover - optional model path
            self.error = f"Could not load NER model from {self.model_dir}: {exc}"
            self._pipeline = None
            self.available = False

    def _outputs_to_predictions(self, outputs: Any) -> list[NerTokenPrediction]:
        predictions: list[NerTokenPrediction] = []
        if not isinstance(outputs, list):
            return predictions
        for item in outputs:
            if not isinstance(item, dict):
                continue
            start = item.get("start")
            end = item.get("end")
            label = item.get("entity") or item.get("entity_group") or item.get("label")
            score = item.get("score", 0.0)
            if start is None or end is None or label is None:
                continue
            try:
                predictions.append(NerTokenPrediction(start=int(start), end=int(end), label=str(label), score=float(score)))
            except (TypeError, ValueError):
                continue
        return predictions
