from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from src.data_types import SpanCandidate, VALID_ENTITY_TYPES
from src.extractors.base import BaseExtractor, ExtractionContext
from src.extractors.utils import make_span_candidate
from src.ner.gliner_backend import GLiNERBackend
from src.ner.gliner_windows import TransformersTokenCounter, build_gliner_windows
from src.ner.prediction_cache import PredictionCache, build_cache_key


DEFAULT_LABEL_MAP = {
    "symptom": "TRIỆU_CHỨNG",
    "disease or diagnosis": "CHẨN_ĐOÁN",
    "medication or drug": "THUỐC",
    "medical test or lab name": "TÊN_XÉT_NGHIỆM",
    "test result or measurement value": "KẾT_QUẢ_XÉT_NGHIỆM",
}


class GLiNERExtractor(BaseExtractor):
    name = "gliner"

    def __init__(self, *, config: Mapping[str, Any] | None = None, backend: GLiNERBackend | None = None) -> None:
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        self.label_map = {str(label): str(entity_type) for label, entity_type in dict(self.config.get("label_map", DEFAULT_LABEL_MAP)).items()}
        invalid_types = set(self.label_map.values()) - VALID_ENTITY_TYPES
        if invalid_types:
            raise ValueError(f"Invalid GLiNER canonical types: {sorted(invalid_types)}")
        self.labels = list(self.label_map)
        threshold_cfg = self.config.get("threshold", 0.35)
        if isinstance(threshold_cfg, Mapping):
            self.default_threshold = float(threshold_cfg.get("default", 0.35))
            self.threshold_by_type = {str(key): float(value) for key, value in threshold_cfg.items() if key != "default"}
        else:
            self.default_threshold = float(threshold_cfg)
            self.threshold_by_type = {}
        self.pass_name = str(self.config.get("pass_name", "full_five_type"))
        window_cfg = dict(self.config.get("windowing", {}))
        self.max_tokens = int(window_cfg.get("max_tokens", 320))
        self.overlap_tokens = int(window_cfg.get("overlap_tokens", 64))
        tokenizer_name = window_cfg.get("tokenizer_name_or_path")
        self.token_counter = TransformersTokenCounter(
            str(tokenizer_name),
            revision=str(window_cfg["tokenizer_revision"]) if window_cfg.get("tokenizer_revision") else None,
            local_files_only=bool(self.config.get("local_files_only", False)),
        ) if self.enabled and tokenizer_name else None
        self.backend = backend
        if self.enabled and self.backend is None:
            self.backend = GLiNERBackend(self.config)
        cache_cfg = dict(self.config.get("cache", {}))
        self.cache = PredictionCache(cache_cfg.get("directory", "outputs/cache/gliner")) if cache_cfg.get("enabled", False) else None

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        if not self.enabled:
            return []
        if self.backend is None:
            raise RuntimeError("GLiNER extractor is enabled without a backend")
        cache_key = self._cache_key(context.raw_text)
        cached = self.cache.get(cache_key) if self.cache else None
        if cached is not None:
            return [_candidate_from_cache(row, context.raw_text) for row in cached]

        candidates: list[SpanCandidate] = []
        windows = build_gliner_windows(
            context.raw_text,
            context.chunks,
            max_tokens=self.max_tokens,
            overlap_tokens=self.overlap_tokens,
            counter=self.token_counter,
        )
        for window in windows:
            for prediction in self.backend.predict(window.text, self.labels, threshold=self._inference_threshold()):
                entity_type = self.label_map.get(prediction.label)
                if entity_type is None or prediction.score < self.threshold_by_type.get(entity_type, self.default_threshold):
                    continue
                start, end = _trim_global_span(context.raw_text, window.start + prediction.start, window.start + prediction.end)
                if start >= end or context.raw_text[start:end] != prediction.text.strip():
                    continue
                candidates.append(
                    make_span_candidate(
                        context.raw_text,
                        start,
                        end,
                        raw_type=entity_type,
                        source="gliner",
                        score=prediction.score,
                        chunk=_chunk_for_window(context.chunks, window.parent_chunk_id),
                        features={
                            "backend": "gliner",
                            "model": self.backend.metadata(),
                            "prompt_label": prediction.label,
                            "canonical_type": entity_type,
                            "pass_name": self.pass_name,
                            "window_id": window.window_id,
                            "parent_chunk_id": window.parent_chunk_id,
                            "local_position": [prediction.start, prediction.end],
                            "global_position": [start, end],
                            "raw_model_score": prediction.score,
                        },
                    )
                )
        deduped = _dedupe_gliner_candidates(candidates)
        if self.cache:
            self.cache.put(cache_key, [_candidate_to_cache(candidate) for candidate in deduped])
        return deduped

    def _inference_threshold(self) -> float:
        return min([self.default_threshold, *self.threshold_by_type.values()])

    def _cache_key(self, raw_text: str) -> str:
        model_metadata = self.backend.metadata() if self.backend else {}
        payload = {
            "input_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "model_hash": hashlib.sha256(repr(sorted(model_metadata.items())).encode("utf-8")).hexdigest(),
            "label_schema_hash": hashlib.sha256(repr(list(self.label_map.items())).encode("utf-8")).hexdigest(),
            "chunking_hash": hashlib.sha256(f"{self.max_tokens}:{self.overlap_tokens}:{type(self.token_counter).__name__}".encode("utf-8")).hexdigest(),
            "threshold_profile_hash": hashlib.sha256(repr((self.default_threshold, sorted(self.threshold_by_type.items()))).encode("utf-8")).hexdigest(),
            "inference_options_hash": hashlib.sha256(self.pass_name.encode("utf-8")).hexdigest(),
        }
        return build_cache_key(payload)


def _trim_global_span(raw_text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    return start, end


def _chunk_for_window(chunks, parent_chunk_id):
    return chunks[parent_chunk_id] if 0 <= parent_chunk_id < len(chunks) else None


def _dedupe_gliner_candidates(candidates: list[SpanCandidate]) -> list[SpanCandidate]:
    grouped: dict[tuple[int, int, str | None], list[SpanCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.start, candidate.end, candidate.raw_type), []).append(candidate)
    output: list[SpanCandidate] = []
    for group in grouped.values():
        winner = max(group, key=lambda candidate: candidate.score)
        features = dict(winner.features)
        features["supporting_windows"] = sorted({str(candidate.features.get("window_id")) for candidate in group})
        features["agreement_count"] = len(group)
        winner.features = features
        output.append(winner)
    return sorted(output, key=lambda candidate: (candidate.start, candidate.end, candidate.raw_type or ""))


def _candidate_to_cache(candidate: SpanCandidate) -> dict[str, Any]:
    return {
        "text": candidate.text,
        "start": candidate.start,
        "end": candidate.end,
        "raw_type": candidate.raw_type,
        "source": candidate.source,
        "score": candidate.score,
        "section": candidate.section,
        "subsection": candidate.subsection,
        "context_left": candidate.context_left,
        "context_right": candidate.context_right,
        "features": candidate.features,
    }


def _candidate_from_cache(row: Mapping[str, Any], raw_text: str) -> SpanCandidate:
    start, end = int(row["start"]), int(row["end"])
    if raw_text[start:end] != row["text"]:
        raise ValueError("Cached GLiNER candidate offset mismatch")
    return SpanCandidate(
        text=str(row["text"]), start=start, end=end, raw_type=row.get("raw_type"), source=str(row["source"]), score=float(row["score"]),
        section=row.get("section"), subsection=row.get("subsection"), context_left=str(row.get("context_left", "")),
        context_right=str(row.get("context_right", "")), features=dict(row.get("features", {})),
    )