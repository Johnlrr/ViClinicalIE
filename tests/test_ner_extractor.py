from __future__ import annotations

from src.data_types import Chunk, TextViews
from src.extractors.base import ExtractionContext
from src.extractors.ner_extractor import NERExtractor
from src.ner.span_decoder import NerTokenPrediction


class FakeRunner:
    available = True
    error = None

    def predict(self, text: str) -> list[NerTokenPrediction]:
        start = text.index("đau")
        return [
            NerTokenPrediction(start, start + 3, "B-TRIỆU_CHỨNG", 0.91),
            NerTokenPrediction(start + 4, start + 8, "I-TRIỆU_CHỨNG", 0.90),
        ]


class MissingRunner:
    available = False
    error = "missing"

    def predict(self, text: str) -> list[NerTokenPrediction]:
        raise AssertionError("predict should not be called")


def test_disabled_ner_extractor_returns_empty() -> None:
    extractor = NERExtractor(config={"enabled": False}, model_runner=FakeRunner())

    assert extractor.extract(_context("Bệnh nhân đau ngực.")) == []


def test_missing_model_returns_empty_without_crash() -> None:
    extractor = NERExtractor(config={"enabled": True}, model_runner=MissingRunner())

    assert extractor.extract(_context("Bệnh nhân đau ngực.")) == []


def test_fake_model_output_returns_valid_candidate() -> None:
    raw = "Bệnh nhân đau ngực."
    extractor = NERExtractor(config={"enabled": True, "threshold": {"TRIỆU_CHỨNG": 0.80}}, model_runner=FakeRunner())

    candidates = extractor.extract(_context(raw))

    assert len(candidates) == 1
    assert candidates[0].text == "đau ngực"
    assert raw[candidates[0].start : candidates[0].end] == candidates[0].text
    assert candidates[0].raw_type == "TRIỆU_CHỨNG"


def test_mock_token_predictions_config_returns_candidate() -> None:
    raw = "Không sốt."
    extractor = NERExtractor(
        config={
            "enabled": True,
            "threshold": {"TRIỆU_CHỨNG": 0.80},
            "mock_token_predictions": [{"start": 6, "end": 9, "label": "B-TRIỆU_CHỨNG", "score": 0.95}],
        },
        model_runner=MissingRunner(),
    )

    candidates = extractor.extract(_context(raw))
    assert [candidate.text for candidate in candidates] == ["sốt"]


def _context(raw: str) -> ExtractionContext:
    return ExtractionContext(
        raw_text=raw,
        views=TextViews(raw=raw, normalized=raw, search=raw, no_diacritics=raw, norm_to_raw=list(range(len(raw))), search_to_raw=list(range(len(raw)))),
        chunks=[Chunk(text=raw, start=0, end=len(raw), section="UNKNOWN")],
    )
