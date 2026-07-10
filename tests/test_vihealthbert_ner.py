"""Tests for offset-safe ViHealthBERT NER inference and decoding."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.preprocessing import TextWindow, preprocess_text
from src.vihealthbert_ner import (
    TokenPrediction,
    ViHealthBERTNER,
    decode_token_predictions,
)


def test_bioes_decoding_preserves_raw_vietnamese_span_and_confidence():
    raw_text = "Bệnh nhân đau ngực dữ dội, sốt."
    predictions = [
        TokenPrediction("O", 0, 4, 0.99),
        TokenPrediction("O", 5, 9, 0.99),
        TokenPrediction("B-TRIỆU_CHỨNG", 10, 13, 0.90),
        TokenPrediction("I-TRIỆU_CHỨNG", 14, 18, 0.80),
        TokenPrediction("E-TRIỆU_CHỨNG", 19, 21, 0.70),
        TokenPrediction("O", 21, 27, 0.99),
        TokenPrediction("S-TRIỆU_CHỨNG", 27, 30, 0.95),
    ]

    candidates = decode_token_predictions(raw_text, "1", predictions)

    assert [(item.text, item.start, item.end, item.type_candidate) for item in candidates] == [
        ("đau ngực dữ", 10, 21, "TRIỆU_CHỨNG"),
        ("sốt", 27, 30, "TRIỆU_CHỨNG"),
    ]
    assert abs(candidates[0].confidence - 0.8) < 1e-9
    assert all(raw_text[item.start:item.end] == item.text for item in candidates)


def test_decoder_repairs_orphan_inside_label_and_type_transition():
    raw_text = "ho viêm phổi"
    predictions = [
        TokenPrediction("I-TRIỆU_CHỨNG", 0, 2, 0.7),
        TokenPrediction("B-CHẨN_ĐOÁN", 3, 7, 0.8),
        TokenPrediction("I-CHẨN_ĐOÁN", 8, 12, 0.9),
    ]

    candidates = decode_token_predictions(raw_text, "2", predictions)

    assert [(item.text, item.type_candidate) for item in candidates] == [
        ("ho", "TRIỆU_CHỨNG"),
        ("viêm phổi", "CHẨN_ĐOÁN"),
    ]


def test_window_inference_maps_local_offsets_and_deduplicates_overlap():
    raw_text = "Tiền sử tăng huyết áp, hiện đau ngực."
    phrase = "tăng huyết áp"
    phrase_start = raw_text.index(phrase)
    windows = [
        TextWindow(raw_text[:30], 0, 30, 0, "model"),
        TextWindow(raw_text[8:], 8, len(raw_text), 1, "model"),
    ]

    def predictor(text):
        start = text.find(phrase)
        if start < 0:
            return []
        return [TokenPrediction("S-CHẨN_ĐOÁN", start, start + len(phrase), 0.91)]

    candidates = ViHealthBERTNER(predictor).predict_windows(raw_text, "3", windows)

    assert len(candidates) == 1
    assert candidates[0].start == phrase_start
    assert candidates[0].end == phrase_start + len(phrase)
    assert candidates[0].text == phrase
    assert raw_text[candidates[0].start:candidates[0].end] == candidates[0].text


def test_type_threshold_filters_low_confidence_candidates():
    raw_text = "đau đầu và aspirin"

    def predictor(text):
        return [
            TokenPrediction("S-TRIỆU_CHỨNG", 0, 7, 0.79),
            TokenPrediction("S-THUỐC", 11, 18, 0.81),
        ]

    ner = ViHealthBERTNER(
        predictor,
        thresholds={"TRIỆU_CHỨNG": 0.80, "THUỐC": 0.80},
    )
    candidates = ner.predict_windows(
        raw_text,
        "4",
        [TextWindow(raw_text, 0, len(raw_text), 0, "model")],
    )

    assert [(item.text, item.type_candidate) for item in candidates] == [("aspirin", "THUỐC")]


def test_predict_preprocessed_uses_offset_safe_model_windows():
    raw_text = "Khám: khó thở khi gắng sức."
    views = preprocess_text(raw_text, max_window_chars=18, overlap_chars=6)

    def predictor(text):
        target = "khó thở"
        start = text.find(target)
        if start < 0:
            return []
        return [TokenPrediction("S-TRIỆU_CHỨNG", start, start + len(target), 0.93)]

    candidates = ViHealthBERTNER(predictor).predict_preprocessed(views, "5")

    assert len(candidates) == 1
    assert candidates[0].text == "khó thở"
    assert raw_text[candidates[0].start:candidates[0].end] == "khó thở"


def test_predictor_offsets_cannot_exceed_window():
    raw_text = "sốt"

    def invalid_predictor(text):
        return [TokenPrediction("S-TRIỆU_CHỨNG", 0, len(text) + 1, 0.9)]

    ner = ViHealthBERTNER(invalid_predictor)
    try:
        ner.predict_windows(raw_text, "6", [TextWindow(raw_text, 0, len(raw_text), 0, "model")])
    except ValueError as error:
        assert "exceeds window" in str(error)
    else:
        raise AssertionError("Expected invalid predictor offsets to raise ValueError")
