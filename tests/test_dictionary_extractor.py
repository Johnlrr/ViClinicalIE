from __future__ import annotations

from src.extractors.base import ExtractionContext
from src.extractors.dictionary_extractor import DictionaryExtractor
from src.preprocess.chunker import preprocess_text


def test_dictionary_extractor_matches_accent_insensitive_span() -> None:
    raw = "Bệnh nhân dau bung và khó thở"
    output = preprocess_text(raw)
    extractor = DictionaryExtractor(entries=[{"alias": "đau bụng", "canonical": "đau bụng", "raw_type": "TRIỆU_CHỨNG"}])

    candidates = extractor.extract(ExtractionContext(raw, output.views, output.chunks))

    assert candidates
    assert candidates[0].text == "dau bung"
    assert raw[candidates[0].start : candidates[0].end] == candidates[0].text


def test_dictionary_extractor_avoids_short_accent_false_positive() -> None:
    raw = "Không có tác dụng phụ được ghi nhận."
    output = preprocess_text(raw)
    extractor = DictionaryExtractor(entries=[{"alias": "phù", "canonical": "phù", "raw_type": "TRIỆU_CHỨNG"}])

    candidates = extractor.extract(ExtractionContext(raw, output.views, output.chunks))

    assert candidates == []
