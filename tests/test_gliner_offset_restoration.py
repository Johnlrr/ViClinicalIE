from __future__ import annotations

from src.data_types import Chunk, TextViews
from src.extractors.base import ExtractionContext
from src.extractors.gliner_extractor import GLiNERExtractor
from src.ner.gliner_backend import GLiNERBackend


class LocalOffsetModel:
    def predict_entities(self, text, labels, *, threshold):
        assert text == "đau ngực"
        return [{"start": 0, "end": 8, "text": text, "label": "symptom", "score": 0.9}]


def test_nonzero_chunk_local_offset_restores_global_raw_position() -> None:
    raw = "Tiền sử:\nđau ngực"
    start = raw.index("đau ngực")
    indexes = list(range(len(raw)))
    context = ExtractionContext(
        raw,
        TextViews(raw, raw, raw, raw, indexes, indexes, indexes),
        [Chunk(raw[start:], start, len(raw), section="PAST_HISTORY")],
    )
    extractor = GLiNERExtractor(
        config={"enabled": True, "threshold": 0.35, "windowing": {"max_tokens": 20, "overlap_tokens": 2}},
        backend=GLiNERBackend({}, model=LocalOffsetModel()),
    )
    candidate = extractor.extract(context)[0]
    assert candidate.start == start
    assert candidate.end == len(raw)
    assert raw[candidate.start:candidate.end] == candidate.text == "đau ngực"