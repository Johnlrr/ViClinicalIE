"""Offset-safe ViHealthBERT token-classification inference for clinical NER.

The module keeps model concerns separate from span decoding. A lightweight predictor
protocol makes BIO/BIOES decoding testable without importing PyTorch or Transformers;
the optional Hugging Face backend imports those dependencies only when instantiated.
All public entity spans use raw-document half-open offsets ``[start, end)``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from importlib import import_module
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from src.models import ClinicalDocument, SpanCandidate
from src.preprocessing import PreprocessedText, TextWindow


ENTITY_TYPES = frozenset(
    {
        "TRIỆU_CHỨNG",
        "CHẨN_ĐOÁN",
        "THUỐC",
        "TÊN_XÉT_NGHIỆM",
        "KẾT_QUẢ_XÉT_NGHIỆM",
    }
)


@dataclass(frozen=True)
class TokenPrediction:
    """One non-special model token with offsets local to its input window."""

    label: str
    start: int
    end: int
    confidence: float

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"Invalid token span [{self.start}, {self.end})")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Token confidence must be between 0 and 1")


class WindowPredictor(Protocol):
    """Backend contract consumed by :class:`ViHealthBERTNER`."""

    def __call__(self, text: str) -> Sequence[TokenPrediction]:
        """Predict labels and local character offsets for one raw-text window."""
        ...


def _parse_label(label: str) -> Tuple[str, Optional[str]]:
    """Return ``(BIOES prefix, entity type)``; unknown labels become outside."""
    normalized = label.strip()
    if normalized.upper() == "O" or "-" not in normalized:
        return "O", None
    prefix, entity_type = normalized.split("-", 1)
    prefix = prefix.upper()
    if prefix not in {"B", "I", "O", "E", "S"} or entity_type not in ENTITY_TYPES:
        return "O", None
    return prefix, entity_type


def decode_token_predictions(
    raw_text: str,
    file_id: str,
    predictions: Sequence[TokenPrediction],
    *,
    offset_base: int = 0,
    source: str = "vihealthbert_ner",
    window_id: Optional[int] = None,
) -> List[SpanCandidate]:
    """Decode BIO or BIOES token labels into raw-document span candidates.

    Malformed transitions are repaired conservatively: an orphan ``I``/``E`` starts
    a new entity, and a type change closes the active entity before starting another.
    Token gaps are retained in the final raw slice, preserving spaces and punctuation
    between subwords exactly as they occurred in the input.
    """
    candidates: List[SpanCandidate] = []
    active_type: Optional[str] = None
    active_start = 0
    active_end = 0
    active_confidences: List[float] = []

    def close_active() -> None:
        nonlocal active_type, active_start, active_end, active_confidences
        if active_type is None:
            return
        start = offset_base + active_start
        end = offset_base + active_end
        if 0 <= start < end <= len(raw_text):
            text = raw_text[start:end]
            confidence = sum(active_confidences) / len(active_confidences)
            candidates.append(
                SpanCandidate(
                    file_id=file_id,
                    text=text,
                    start=start,
                    end=end,
                    type_candidate=active_type,
                    source=[source],
                    confidence=confidence,
                    notes="" if window_id is None else f"model_window={window_id}",
                )
            )
        active_type = None
        active_confidences = []

    for token in sorted(predictions, key=lambda item: (item.start, item.end)):
        if token.end <= token.start:
            continue
        prefix, entity_type = _parse_label(token.label)
        if prefix == "O" or entity_type is None:
            close_active()
            continue

        starts_entity = prefix in {"B", "S"}
        incompatible = active_type is not None and active_type != entity_type
        orphan = active_type is None and prefix in {"I", "E"}
        if starts_entity or incompatible or orphan:
            close_active()
            active_type = entity_type
            active_start = token.start
            active_end = token.end
            active_confidences = [token.confidence]
        elif active_type is None:
            active_type = entity_type
            active_start = token.start
            active_end = token.end
            active_confidences = [token.confidence]
        else:
            active_end = max(active_end, token.end)
            active_confidences.append(token.confidence)

        if prefix in {"E", "S"}:
            close_active()

    close_active()
    return candidates


def deduplicate_ner_candidates(candidates: Iterable[SpanCandidate]) -> List[SpanCandidate]:
    """Merge exact predictions from overlapping windows, keeping best confidence."""
    best: Dict[Tuple[str, int, int, str], SpanCandidate] = {}
    for candidate in candidates:
        key = (candidate.file_id, candidate.start, candidate.end, candidate.type_candidate)
        previous = best.get(key)
        if previous is None:
            best[key] = candidate
            continue
        sources = list(dict.fromkeys([*previous.source, *candidate.source]))
        winner = candidate if candidate.confidence > previous.confidence else previous
        best[key] = replace(winner, source=sources)
    return sorted(best.values(), key=lambda item: (item.start, item.end, item.type_candidate))


class ViHealthBERTNER:
    """Windowed, offset-preserving NER candidate generator."""

    def __init__(
        self,
        predictor: WindowPredictor,
        *,
        thresholds: Optional[Mapping[str, float]] = None,
        source: str = "vihealthbert_ner",
    ) -> None:
        self.predictor = predictor
        self.thresholds = dict(thresholds or {})
        self.source = source

    def predict_windows(
        self,
        raw_text: str,
        file_id: str,
        windows: Sequence[TextWindow],
    ) -> List[SpanCandidate]:
        """Run inference over raw windows and deduplicate overlap predictions."""
        candidates: List[SpanCandidate] = []
        for window in windows:
            predictions = self.predictor(window.text)
            for token in predictions:
                if token.end > len(window.text):
                    raise ValueError(
                        f"Predictor token [{token.start}, {token.end}) exceeds window {window.window_id}"
                    )
            candidates.extend(
                decode_token_predictions(
                    raw_text,
                    file_id,
                    predictions,
                    offset_base=window.start,
                    source=self.source,
                    window_id=window.window_id,
                )
            )

        filtered = [
            candidate
            for candidate in candidates
            if candidate.confidence >= self.thresholds.get(candidate.type_candidate, 0.0)
            and raw_text[candidate.start:candidate.end] == candidate.text
        ]
        return deduplicate_ner_candidates(filtered)

    def predict_preprocessed(self, views: PreprocessedText, file_id: str) -> List[SpanCandidate]:
        """Predict from preprocessing views, preferring model windows."""
        windows = views.model_windows or views.sentence_windows
        if not windows and views.raw_text:
            windows = [TextWindow(views.raw_text, 0, len(views.raw_text), 0, "model")]
        return self.predict_windows(views.raw_text, file_id, windows)

    def predict_document(self, document: ClinicalDocument) -> List[SpanCandidate]:
        """Predict directly from a preprocessed clinical document."""
        windows = document.model_windows or document.sentence_windows
        if not windows and document.raw_text:
            windows = [TextWindow(document.raw_text, 0, len(document.raw_text), 0, "model")]
        return self.predict_windows(document.raw_text, document.file_id, windows)


class HuggingFaceTokenPredictor:
    """Optional Hugging Face backend for a fine-tuned ViHealthBERT checkpoint.

    The checkpoint must expose token-classification ``id2label`` metadata and use a
    fast tokenizer so that character ``offset_mapping`` is available.
    """

    def __init__(
        self,
        model_name_or_path: str,
        *,
        device: Optional[str] = None,
        max_length: int = 512,
    ) -> None:
        try:
            torch = import_module("torch")
            transformers = import_module("transformers")
        except ImportError as error:
            raise ImportError(
                "HuggingFaceTokenPredictor requires optional dependencies "
                "'torch' and 'transformers'"
            ) from error

        self._torch = torch
        auto_tokenizer = transformers.AutoTokenizer
        auto_model = transformers.AutoModelForTokenClassification
        self.tokenizer = auto_tokenizer.from_pretrained(model_name_or_path, use_fast=True)
        if not self.tokenizer.is_fast:
            raise ValueError("A fast tokenizer is required for raw character offset mapping")
        self.model = auto_model.from_pretrained(model_name_or_path)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
        self.max_length = max_length
        self.id2label = {
            int(index): label for index, label in self.model.config.id2label.items()
        }

    def __call__(self, text: str) -> Sequence[TokenPrediction]:
        """Return per-token labels with offsets local to ``text``."""
        encoded = self.tokenizer(
            text,
            return_offsets_mapping=True,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        )
        offsets = encoded.pop("offset_mapping")[0].tolist()
        model_inputs = {name: value.to(self.device) for name, value in encoded.items()}
        with self._torch.inference_mode():
            logits = self.model(**model_inputs).logits[0]
            probabilities = self._torch.softmax(logits, dim=-1)
            confidence_values, label_ids = probabilities.max(dim=-1)

        predictions: List[TokenPrediction] = []
        for (start, end), label_id, confidence in zip(
            offsets,
            label_ids.tolist(),
            confidence_values.tolist(),
        ):
            if end <= start:
                continue
            predictions.append(
                TokenPrediction(
                    label=self.id2label.get(int(label_id), "O"),
                    start=int(start),
                    end=int(end),
                    confidence=float(confidence),
                )
            )
        return predictions
