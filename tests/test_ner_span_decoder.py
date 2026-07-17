from __future__ import annotations

from src.ner.span_decoder import NerTokenPrediction, decode_token_predictions


def test_decode_token_predictions_builds_span_candidate() -> None:
    raw = "Bệnh nhân đau ngực hôm nay."
    predictions = [
        NerTokenPrediction(10, 13, "B-TRIỆU_CHỨNG", 0.91),
        NerTokenPrediction(14, 18, "I-TRIỆU_CHỨNG", 0.89),
    ]

    candidates = decode_token_predictions(raw, predictions, threshold_by_type={"TRIỆU_CHỨNG": 0.85})

    assert len(candidates) == 1
    assert candidates[0].text == "đau ngực"
    assert candidates[0].raw_type == "TRIỆU_CHỨNG"
    assert candidates[0].source == "ner"


def test_decode_token_predictions_drops_low_confidence() -> None:
    raw = "Bệnh nhân đau ngực."
    predictions = [NerTokenPrediction(10, 18, "B-TRIỆU_CHỨNG", 0.50)]

    candidates = decode_token_predictions(raw, predictions, threshold_by_type={"TRIỆU_CHỨNG": 0.85})

    assert candidates == []


def test_decode_token_predictions_rejects_too_long_span() -> None:
    raw = "a" * 130
    predictions = [NerTokenPrediction(0, 130, "B-CHẨN_ĐOÁN", 0.99)]

    candidates = decode_token_predictions(raw, predictions, max_entity_chars={"CHẨN_ĐOÁN": 120})

    assert candidates == []


def test_decode_token_predictions_splits_different_types() -> None:
    raw = "sốt viêm phổi"
    predictions = [
        NerTokenPrediction(0, 3, "B-TRIỆU_CHỨNG", 0.9),
        NerTokenPrediction(4, 13, "B-CHẨN_ĐOÁN", 0.9),
    ]

    candidates = decode_token_predictions(raw, predictions)

    assert [candidate.text for candidate in candidates] == ["sốt", "viêm phổi"]
