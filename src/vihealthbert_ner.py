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

from src.models import ClinicalDocument, Line, SpanCandidate
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

DEFAULT_BIO_ID2LABEL: Dict[int, str] = {
    0: "O",
    1: "B-TRIỆU_CHỨNG",
    2: "I-TRIỆU_CHỨNG",
    3: "B-CHẨN_ĐOÁN",
    4: "I-CHẨN_ĐOÁN",
    5: "B-THUỐC",
    6: "I-THUỐC",
    7: "B-TÊN_XÉT_NGHIỆM",
    8: "I-TÊN_XÉT_NGHIỆM",
    9: "B-KẾT_QUẢ_XÉT_NGHIỆM",
    10: "I-KẾT_QUẢ_XÉT_NGHIỆM",
}


# ---------------------------------------------------------------------------
# VietMed label adapter (plan_ner.md)
# ---------------------------------------------------------------------------
# Active only when ``ViHealthBERTNER(label_map="vietmed")`` is configured. The
# raw VietMed checkpoint (leduckhai/VietMed-NER) emits coarse clinical labels
# (DRUGCHEMICAL, DIAGNOSTICS, UNITCALIBRATOR, DISEASESYMTOM, ...). High-signal
# types map directly to submission types; the ambiguous DISEASESYMTOM type is
# kept as a pending temporary type and routed to CHẨN_ĐOÁN or TRIỆU_CHỨNG using
# section context after decoding. Unknown / non-target labels drop to outside.
VIETMED_TO_SUBMISSION: Dict[str, str] = {
    "DRUGCHEMICAL": "THUỐC",
    "DIAGNOSTICS": "TÊN_XÉT_NGHIỆM",
    "UNITCALIBRATOR": "KẾT_QUẢ_XÉT_NGHIỆM",
}

# Temporary entity type used to carry a raw DISEASESYMTOM span through the
# BIO decoder until section context can resolve it to a submission type.
_DISEASESYMTOM_PENDING = "_DISEASESYMTOM_PENDING"
_TEMP_ENTITY_TYPES = frozenset({_DISEASESYMTOM_PENDING})

# Sections where a pending DISEASESYMTOM span is most likely a diagnosis.
# Mirrors src/rule_extractors.py:DIAGNOSIS_SUBSECTIONS / DIAGNOSIS_SECTIONS.
_DIAGNOSIS_SUBSECTIONS = frozenset(
    {
        "CHRONIC_DISEASES",
        "DIAGNOSTIC_FINDINGS",
        "LAB_RESULT_SECTION",
        "IMAGING_RESULT_SECTION",
    }
)
_DIAGNOSIS_SECTION_TYPES = frozenset(
    {
        "PAST_HISTORY",
        "HOSPITAL_ASSESSMENT",
    }
)
# Sections where a pending DISEASESYMTOM span is most likely a symptom.
# Mirrors src/rule_extractors.py:SYMPTOM_SUBSECTIONS.
_SYMPTOM_SUBSECTIONS = frozenset(
    {
        "ADMISSION_REASON",
        "CURRENT_SYMPTOMS",
        "SYMPTOM_DETAIL",
        "IMMEDIATE_PRE_ADMISSION_STATUS",
    }
)
_SYMPTOM_SECTION_TYPES = frozenset(
    {
        "CURRENT_HISTORY",
    }
)

# Conservative per-type thresholds for the VietMed adapter (plan_ner.md §5).
VIETMED_DEFAULT_THRESHOLDS: Dict[str, float] = {
    "THUỐC": 0.75,
    "TÊN_XÉT_NGHIỆM": 0.70,
    "KẾT_QUẢ_XÉT_NGHIỆM": 0.80,
    "CHẨN_ĐOÁN": 0.80,
    "TRIỆU_CHỨNG": 0.80,
}


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


class FastTokenizerRequiredError(ValueError):
    """Raised when a checkpoint cannot provide fast-tokenizer offsets."""


def _has_hf_file(model_name_or_path: str, filename: str) -> bool:
    """Return whether a local path or Hugging Face repo exposes ``filename``."""
    try:
        from pathlib import Path

        path = Path(model_name_or_path)
        if path.exists():
            return (path / filename).exists()
    except OSError:
        return False

    try:
        hf_hub_download = import_module("huggingface_hub").hf_hub_download
        hf_hub_download(model_name_or_path, filename, local_files_only=True)
        return True
    except Exception:
        try:
            hf_hub_download(model_name_or_path, filename)
            return True
        except Exception:
            return False


def _normalize_phobert_token(token: str) -> Tuple[str, bool]:
    """Return text to align for a PhoBERT/BPE token and whether it continues."""
    if token.endswith("@@"):
        return token[:-2], True
    return token, False


def _align_slow_tokens_to_text(text: str, tokens: Sequence[str]) -> List[Tuple[int, int]]:
    """Best-effort offsets for slow PhoBERT tokens that lack offset_mapping.

    PhoBERT uses BPE continuation markers (``@@``). We align token surfaces back to
    the original window from left to right. This keeps raw offsets usable for the
    repository's decoder when a checkpoint only ships a slow tokenizer.
    """
    offsets: List[Tuple[int, int]] = []
    cursor = 0
    for token in tokens:
        piece, continues = _normalize_phobert_token(token)
        if not piece:
            offsets.append((0, 0))
            continue
        start = text.find(piece, cursor)
        if start < 0:
            offsets.append((0, 0))
            continue
        end = start + len(piece)
        offsets.append((start, end))
        cursor = end if continues else end
    return offsets


def _parse_label(label: str) -> Tuple[str, Optional[str]]:
    """Return ``(BIOES prefix, entity type)``; unknown labels become outside.

    Submission entity types and the temporary ``_DISEASESYMTOM_PENDING`` marker
    used by the VietMed adapter are both accepted. Any other entity type drops
    to outside so the decoder never emits a non-target span.
    """
    normalized = label.strip()
    if normalized.upper() == "O" or "-" not in normalized:
        return "O", None
    prefix, entity_type = normalized.split("-", 1)
    prefix = prefix.upper()
    if prefix not in {"B", "I", "O", "E", "S"} or (
        entity_type not in ENTITY_TYPES and entity_type not in _TEMP_ENTITY_TYPES
    ):
        return "O", None
    return prefix, entity_type


def map_vietmed_label(label: str) -> str:
    """Map a raw VietMed BIO label to a submission BIO label.

    The VietMed checkpoint (``leduckhai/VietMed-NER``) emits coarse clinical
    labels. High-signal types map directly to submission types:

    - ``B/I-DRUGCHEMICAL`` -> ``B/I-THUỐC``
    - ``B/I-DIAGNOSTICS`` -> ``B/I-TÊN_XÉT_NGHIỆM``
    - ``B/I-UNITCALIBRATOR`` -> ``B/I-KẾT_QUẢ_XÉT_NGHIỆM``

    The ambiguous ``DISEASESYMTOM`` type is preserved as a pending temporary
    marker (``B/I-_DISEASESYMTOM_PENDING``) so the decoder can assemble the full
    span before :func:`route_diseasesyptom_candidates` resolves it to
    ``CHẨN_ĐOÁN`` or ``TRIỆU_CHỨNG`` using section context.

    The literal string ``"0"`` (VietMed ``id2label`` index 22) and any
    unknown / non-target label map to ``"O"``. The BIOES prefix (``B``/``I``/
    ``E``/``S``) is always preserved.
    """
    normalized = label.strip()
    if normalized.upper() == "O":
        return "O"
    if normalized == "0":
        return "O"
    if "-" not in normalized:
        return "O"
    prefix, coarse = normalized.split("-", 1)
    prefix = prefix.upper()
    if prefix not in {"B", "I", "E", "S"}:
        return "O"
    if coarse == "DISEASESYMTOM":
        return f"{prefix}-{_DISEASESYMTOM_PENDING}"
    mapped = VIETMED_TO_SUBMISSION.get(coarse)
    if mapped is None:
        return "O"
    return f"{prefix}-{mapped}"


def _route_diseasesyptom_by_context(
    section_type: Optional[str],
    subsection_type: Optional[str],
) -> str | None:
    """Pick CHẨN_ĐOÁN or TRIỆU_CHỨNG for a pending DISEASESYMTOM span.

    Returns ``None`` when no high-confidence section context is available so
    the caller can drop the span (conservative default per plan_ner.md §2).
    """
    if (
        subsection_type in _DIAGNOSIS_SUBSECTIONS
        or section_type in _DIAGNOSIS_SECTION_TYPES
    ):
        return "CHẨN_ĐOÁN"
    if subsection_type in _SYMPTOM_SUBSECTIONS or section_type in _SYMPTOM_SECTION_TYPES:
        return "TRIỆU_CHỨNG"
    return None


def route_diseasesyptom_candidates(
    candidates: Sequence[SpanCandidate],
    lines: Sequence[Line],
    *,
    drop_without_context: bool = True,
) -> List[SpanCandidate]:
    """Resolve pending ``_DISEASESYMTOM_PENDING`` candidates to a target type.

    Non-pending candidates are returned unchanged. For each pending candidate
    the function first trusts any section/subsection already attached to the
    candidate; otherwise it overlaps the candidate span against parsed document
    ``lines`` to derive the enclosing line's section/subsection. If the context
    maps to a diagnosis section the candidate becomes ``CHẨN_ĐOÁN``; if it maps
    to a symptom section it becomes ``TRIỆU_CHỨNG``; otherwise the candidate is
    dropped (or kept as pending when ``drop_without_context`` is False).
    """
    if not candidates:
        return []
    sorted_lines = sorted(lines, key=lambda line: line.start) if lines else []
    result: List[SpanCandidate] = []
    for candidate in candidates:
        if candidate.type_candidate != _DISEASESYMTOM_PENDING:
            result.append(candidate)
            continue

        section_type = candidate.section_type
        subsection_type = candidate.subsection_type
        if section_type is None and subsection_type is None and sorted_lines:
            for line in sorted_lines:
                if line.start <= candidate.start < line.end:
                    section_type = line.section_type
                    subsection_type = line.subsection_type
                    break
                if candidate.start <= line.start < candidate.end:
                    section_type = line.section_type
                    subsection_type = line.subsection_type
                    break

        routed = _route_diseasesyptom_by_context(section_type, subsection_type)
        if routed is None:
            if drop_without_context:
                continue
            result.append(candidate)
            continue
        result.append(replace(candidate, type_candidate=routed))
    return result


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
        label_map: str = "compact",
    ) -> None:
        self.predictor = predictor
        self.thresholds = dict(thresholds or {})
        self.source = source
        self.label_map = label_map
        if label_map not in {"compact", "vietmed"}:
            raise ValueError(f"unknown NER label_map: {label_map!r}")

    def predict_windows(
        self,
        raw_text: str,
        file_id: str,
        windows: Sequence[TextWindow],
        *,
        lines: Sequence[Line] = (),
    ) -> List[SpanCandidate]:
        """Run inference over raw windows and deduplicate overlap predictions.

        When ``self.label_map == "vietmed"`` is configured, raw VietMed BIO
        labels are first mapped to submission types (or to the pending
        ``_DISEASESYMTOM_PENDING`` marker for the ambiguous DISEASESYMTOM type)
        before decoding. After decoding, pending candidates are routed to
        ``CHẨN_ĐOÁN``/``TRIỆU_CHỨNG`` using document ``lines`` for section
        context. Callers like :meth:`predict_document` should pass parsed
        ``lines`` so section routing can fire.
        """
        candidates: List[SpanCandidate] = []
        for window in windows:
            predictions = self.predictor(window.text)
            for token in predictions:
                if token.end > len(window.text):
                    raise ValueError(
                        f"Predictor token [{token.start}, {token.end}) exceeds window {window.window_id}"
                    )
            if self.label_map == "vietmed":
                predictions = [replace(p, label=map_vietmed_label(p.label)) for p in predictions]
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

        if self.label_map == "vietmed":
            # Always run routing in vietmed mode; drop_without_context=True
            # ensures pending DISEASESYMTOM candidates with no section context
            # are conservatively removed instead of leaking through the filter.
            candidates = route_diseasesyptom_candidates(candidates, lines)

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
        """Predict directly from a preprocessed clinical document.

        Passes ``document.lines`` so the VietMed adapter can route pending
        ``DISEASESYMTOM`` candidates using section context.
        """
        windows = document.model_windows or document.sentence_windows
        if not windows and document.raw_text:
            windows = [TextWindow(document.raw_text, 0, len(document.raw_text), 0, "model")]
        return self.predict_windows(
            document.raw_text, document.file_id, windows, lines=document.lines
        )


class HuggingFaceTokenPredictor:
    """Optional Hugging Face backend for a fine-tuned ViHealthBERT checkpoint.

    The checkpoint should expose token-classification ``id2label`` metadata. PEFT
    adapter-only checkpoints are supported when they include ``adapter_config.json``.
    Fast tokenizer offsets are preferred; slow PhoBERT tokenizers are aligned back
    to raw text as a fallback.
    """

    def __init__(
        self,
        model_name_or_path: str,
        *,
        device: Optional[str] = None,
        max_length: int = 512,
        label_map: str = "compact",
    ) -> None:
        model_name_or_path = model_name_or_path.strip()
        if label_map not in {"compact", "vietmed"}:
            raise ValueError(f"unknown NER label_map: {label_map!r}")
        self.label_map = label_map
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

        label2id = {label: index for index, label in DEFAULT_BIO_ID2LABEL.items()}
        if _has_hf_file(model_name_or_path, "adapter_config.json"):
            try:
                peft = import_module("peft")
            except ImportError as error:
                raise ImportError(
                    "PEFT adapter checkpoint detected but optional dependency 'peft' "
                    "is not installed. Run: python -m pip install peft"
                ) from error
            # Only force the project's compact BIO label space onto PEFT adapters
            # when running in compact mode. In vietmed mode the checkpoint owns
            # its own coarse label space and must not be overwritten.
            peft_kwargs: Dict[str, object] = {}
            if label_map == "compact":
                peft_kwargs.update(
                    num_labels=len(DEFAULT_BIO_ID2LABEL),
                    id2label=DEFAULT_BIO_ID2LABEL,
                    label2id=label2id,
                )
            self.model = peft.AutoPeftModelForTokenClassification.from_pretrained(
                model_name_or_path,
                **peft_kwargs,
            )
        else:
            self.model = auto_model.from_pretrained(model_name_or_path)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
        self.max_length = max_length
        raw_id2label = getattr(self.model.config, "id2label", None) or DEFAULT_BIO_ID2LABEL
        self.id2label = {int(index): label for index, label in raw_id2label.items()}

    def __call__(self, text: str) -> Sequence[TokenPrediction]:
        """Return per-token labels with offsets local to ``text``."""
        encoded = self.tokenizer(
            text,
            return_offsets_mapping=True,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_length,
        )
        offset_mapping = encoded.pop("offset_mapping", None)
        if offset_mapping is not None:
            offsets = offset_mapping[0].tolist()
        else:
            tokens = self.tokenizer.convert_ids_to_tokens(encoded["input_ids"][0].tolist())
            offsets = _align_slow_tokens_to_text(text, tokens)
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
