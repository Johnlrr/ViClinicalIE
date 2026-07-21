from __future__ import annotations

from src.data_types import Chunk, TextViews
from src.extractors.base import ExtractionContext
from src.extractors.gliner_extractor import GLiNERExtractor
from src.ner.gliner_backend import GLiNERBackend


class FakeModel:
    calls = 0

    def predict_entities(self, text, labels, *, threshold):
        self.calls += 1
        start = text.find("đau ngực")
        return [] if start < 0 else [{"start": start, "end": start + 8, "text": "đau ngực", "label": "symptom", "score": 0.9}]


def _context(raw: str) -> ExtractionContext:
    indexes = list(range(len(raw)))
    views = TextViews(raw, raw, raw, raw, indexes, indexes, indexes)
    return ExtractionContext(raw, views, [Chunk(raw, 0, len(raw), section="CURRENT")])


def test_extractor_restores_offset_and_provenance() -> None:
    raw = "Bệnh nhân đau ngực."
    backend = GLiNERBackend({}, model=FakeModel())
    extractor = GLiNERExtractor(config={"enabled": True, "threshold": 0.35, "windowing": {"max_tokens": 20, "overlap_tokens": 2}}, backend=backend)
    candidates = extractor.extract(_context(raw))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert raw[candidate.start:candidate.end] == "đau ngực"
    assert candidate.raw_type == "TRIỆU_CHỨNG"
    assert candidate.source == "gliner"
    assert candidate.features["window_id"] == "c0:w0"


def test_overlap_windows_deduplicate_exact_prediction() -> None:
    raw = "a b đau ngực c d"
    backend = GLiNERBackend({}, model=FakeModel())
    extractor = GLiNERExtractor(config={"enabled": True, "threshold": 0.35, "windowing": {"max_tokens": 5, "overlap_tokens": 3}}, backend=backend)
    candidates = extractor.extract(_context(raw))
    assert len(candidates) == 1
    assert candidates[0].features["agreement_count"] == 2


def test_disabled_extractor_does_not_construct_backend() -> None:
    extractor = GLiNERExtractor(config={"enabled": False, "required": True, "model_name_or_path": "missing"})
    assert extractor.backend is None
    assert extractor.extract(_context("đau ngực")) == []


def test_cache_hit_does_not_call_model(tmp_path) -> None:
    raw = "Bệnh nhân đau ngực."
    model = FakeModel()
    backend = GLiNERBackend({}, model=model)
    config = {
        "enabled": True,
        "threshold": 0.35,
        "windowing": {"max_tokens": 20, "overlap_tokens": 2},
        "cache": {"enabled": True, "directory": str(tmp_path)},
    }
    first = GLiNERExtractor(config=config, backend=backend).extract(_context(raw))
    calls_after_first = model.calls
    second = GLiNERExtractor(config=config, backend=backend).extract(_context(raw))
    assert second == first
    assert model.calls == calls_after_first