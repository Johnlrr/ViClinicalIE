"""Tests for offset-safe ViHealthBERT NER inference and decoding."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import ClinicalDocument, Line, SpanCandidate
from src.preprocessing import TextWindow, preprocess_text
from src.vihealthbert_ner import (
    FastTokenizerRequiredError,
    VIETMED_DEFAULT_THRESHOLDS,
    TokenPrediction,
    ViHealthBERTNER,
    decode_token_predictions,
    map_vietmed_label,
    route_diseasesyptom_candidates,
)
from scripts import build_new_arch_outputs


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


def test_run_ner_falls_back_when_checkpoint_has_no_fast_tokenizer(monkeypatch, capsys):
    """Pipeline should continue without NER seeds for slow-tokenizer checkpoints."""

    def unavailable_predictor(*args, **kwargs):
        raise FastTokenizerRequiredError("slow tokenizer")

    monkeypatch.setattr(build_new_arch_outputs, "HuggingFaceTokenPredictor", unavailable_predictor)

    candidates = build_new_arch_outputs.run_ner(
        [ClinicalDocument(file_id="1", raw_text="Bệnh nhân đau ngực.")],
        model_name_or_path="dummy-slow-tokenizer-checkpoint",
        device=None,
        max_length=512,
        thresholds={},
        skip_ner=False,
    )

    assert candidates == []
    assert "NER disabled: slow tokenizer" in capsys.readouterr().out


def test_run_ner_strict_reraises_fast_tokenizer_error(monkeypatch):
    """Strict mode keeps fail-fast behavior for diagnosing model packaging issues."""

    def unavailable_predictor(*args, **kwargs):
        raise FastTokenizerRequiredError("slow tokenizer")

    monkeypatch.setattr(build_new_arch_outputs, "HuggingFaceTokenPredictor", unavailable_predictor)

    try:
        build_new_arch_outputs.run_ner(
            [ClinicalDocument(file_id="1", raw_text="Bệnh nhân đau ngực.")],
            model_name_or_path="dummy-slow-tokenizer-checkpoint",
            device=None,
            max_length=512,
            thresholds={},
            skip_ner=False,
            strict=True,
        )
    except FastTokenizerRequiredError as error:
        assert "slow tokenizer" in str(error)
    else:
        raise AssertionError("Expected strict NER mode to re-raise FastTokenizerRequiredError")


def test_run_ner_falls_back_on_general_backend_init_failure(monkeypatch, capsys):
    """Bad/missing/private model ids should not stop non-strict parser-only runs."""

    def unavailable_predictor(*args, **kwargs):
        raise OSError("model not found")

    monkeypatch.setattr(build_new_arch_outputs, "HuggingFaceTokenPredictor", unavailable_predictor)

    candidates = build_new_arch_outputs.run_ner(
        [ClinicalDocument(file_id="1", raw_text="Bệnh nhân đau ngực.")],
        model_name_or_path="missing-model",
        device=None,
        max_length=512,
        thresholds={},
        skip_ner=False,
    )

    assert candidates == []
    output = capsys.readouterr().out
    assert "NER disabled: could not initialize Hugging Face backend" in output
    assert "model not found" in output


def test_map_vietmed_label_high_signal_types():
    """High-signal VietMed labels map directly to submission BIO labels."""
    assert map_vietmed_label("B-DRUGCHEMICAL") == "B-THUỐC"
    assert map_vietmed_label("I-DRUGCHEMICAL") == "I-THUỐC"
    assert map_vietmed_label("B-DIAGNOSTICS") == "B-TÊN_XÉT_NGHIỆM"
    assert map_vietmed_label("I-DIAGNOSTICS") == "I-TÊN_XÉT_NGHIỆM"
    assert map_vietmed_label("B-UNITCALIBRATOR") == "B-KẾT_QUẢ_XÉT_NGHIỆM"
    assert map_vietmed_label("I-UNITCALIBRATOR") == "I-KẾT_QUẢ_XÉT_NGHIỆM"
    assert map_vietmed_label("E-DIAGNOSTICS") == "E-TÊN_XÉT_NGHIỆM"
    assert map_vietmed_label("S-DRUGCHEMICAL") == "S-THUỐC"


def test_map_vietmed_label_diseasesyptom_marks_pending():
    """DISEASESYMTOM is preserved as a pending type until section routing."""
    assert map_vietmed_label("B-DISEASESYMTOM") == "B-_DISEASESYMTOM_PENDING"
    assert map_vietmed_label("I-DISEASESYMTOM") == "I-_DISEASESYMTOM_PENDING"


def test_map_vietmed_label_drops_non_target_and_zero():
    """Non-target labels and the literal '0' (VietMed index 22) drop to 'O'."""
    assert map_vietmed_label("0") == "O"
    assert map_vietmed_label("O") == "O"
    assert map_vietmed_label("  o  ") == "O"
    assert map_vietmed_label("B-PREVENTIVEMED") == "O"
    assert map_vietmed_label("B-SURGERY") == "O"
    assert map_vietmed_label("B-TREATMENT") == "O"
    assert map_vietmed_label("B-AGE") == "O"
    assert map_vietmed_label("X-BOGUS") == "O"
    assert map_vietmed_label("not-a-label") == "O"


def test_diseasesyptom_routing_diagnosis_and_symptom_context():
    """Same raw span becomes CHẨN_ĐOÁN in diagnosis sections and TRIỆU_CHỨNG in symptom sections."""
    pending = [
        SpanCandidate(
            file_id="f1",
            text="đái tháo đường",
            start=20,
            end=35,
            type_candidate="_DISEASESYMTOM_PENDING",
            source=["vihealthbert_ner"],
            confidence=0.85,
        ),
        SpanCandidate(
            file_id="f1",
            text="đau ngực",
            start=80,
            end=87,
            type_candidate="_DISEASESYMTOM_PENDING",
            source=["vihealthbert_ner"],
            confidence=0.85,
        ),
    ]
    lines = [
        Line(text="các bệnh mãn tính:", start=0, end=20, line_kind="header",
             section_type="PAST_HISTORY", subsection_type="CHRONIC_DISEASES"),
        Line(text="đái tháo đường", start=20, end=35, line_kind="free_text",
             section_type="PAST_HISTORY", subsection_type="CHRONIC_DISEASES"),
        Line(text="triệu chứng hiện tại:", start=70, end=90, line_kind="header",
             section_type="CURRENT_HISTORY", subsection_type="CURRENT_SYMPTOMS"),
        Line(text="đau ngực", start=80, end=87, line_kind="free_text",
             section_type="CURRENT_HISTORY", subsection_type="CURRENT_SYMPTOMS"),
    ]
    resolved = route_diseasesyptom_candidates(pending, lines)
    assert [(item.text, item.type_candidate) for item in resolved] == [
        ("đái tháo đường", "CHẨN_ĐOÁN"),
        ("đau ngực", "TRIỆU_CHỨNG"),
    ]


def test_diseasesyptom_routing_drops_without_context():
    """Pending DISEASESYMTOM spans with no matching section context are dropped."""
    pending = [
        SpanCandidate(
            file_id="f2",
            text="ung thư phổi",
            start=10,
            end=20,
            type_candidate="_DISEASESYMTOM_PENDING",
            source=["vihealthbert_ner"],
            confidence=0.85,
        )
    ]
    lines = [
        Line(text="khác", start=0, end=5, line_kind="free_text", section_type="UNKNOWN"),
    ]
    assert route_diseasesyptom_candidates(pending, lines) == []


def test_vietmed_label_map_pipeline_decodes_drugs_diag_lab():
    """End-to-end: raw VietMed predictions yield THUỐC/TÊN_XÉT_NGHIỆM/TRIỆU_CHỨNG spans."""
    raw_text = "Bệnh nhân đau ngực, dùng aspirin. Xét nghiệm CRP."

    def predictor(text: str):
        hits = []
        if (idx := text.find("aspirin")) >= 0:
            hits.append(TokenPrediction("B-DRUGCHEMICAL", idx, idx + len("aspirin"), 0.92))
        if (idx := text.find("CRP")) >= 0:
            hits.append(TokenPrediction("B-DIAGNOSTICS", idx, idx + len("CRP"), 0.81))
        if (idx := text.find("đau ngực")) >= 0:
            hits.append(TokenPrediction("B-DISEASESYMTOM", idx, idx + len("đau ngực"), 0.86))
        return hits

    ner = ViHealthBERTNER(
        predictor,
        thresholds=VIETMED_DEFAULT_THRESHOLDS,
        label_map="vietmed",
    )
    documents_by_lines = [
        Line(text=raw_text, start=0, end=len(raw_text), line_kind="free_text",
             section_type="CURRENT_HISTORY", subsection_type="CURRENT_SYMPTOMS"),
    ]
    candidates = ner.predict_windows(
        raw_text,
        "f3",
        [TextWindow(raw_text, 0, len(raw_text), 0, "model")],
        lines=documents_by_lines,
    )
    assert [(item.text, item.type_candidate) for item in candidates] == [
        ("đau ngực", "TRIỆU_CHỨNG"),
        ("aspirin", "THUỐC"),
        ("CRP", "TÊN_XÉT_NGHIỆM"),
    ]
    for candidate in candidates:
        assert raw_text[candidate.start:candidate.end] == candidate.text


def test_vietmed_label_map_drops_non_target_labels():
    """Non-target VietMed labels never produce a submission span."""
    raw_text = "Bệnh nhân 60 tuổi, tại Hà Nội."

    def predictor(text: str):
        idx = text.find("60")
        return [TokenPrediction("B-AGE", idx, idx + 2, 0.99)]

    ner = ViHealthBERTNER(predictor, thresholds={"AGE": 0.0}, label_map="vietmed")
    candidates = ner.predict_windows(
        raw_text,
        "f4",
        [TextWindow(raw_text, 0, len(raw_text), 0, "model")],
    )
    assert candidates == []


def test_vietmed_label_map_drops_pending_without_section_context():
    """Pending DISEASESYMTOM in unknown context is dropped conservatively."""
    raw_text = "Tình trạng tổng quát ổn định."

    def predictor(text: str):
        idx = text.find("tổng quát")
        return [TokenPrediction("B-DISEASESYMTOM", idx, idx + len("tổng quát"), 0.84)]

    ner = ViHealthBERTNER(predictor, thresholds={}, label_map="vietmed")
    candidates = ner.predict_windows(
        raw_text,
        "f5",
        [TextWindow(raw_text, 0, len(raw_text), 0, "model")],
        lines=[],
    )
    assert candidates == []


def test_compact_label_map_unchanged_by_default():
    """Default label_map='compact' keeps existing behavior; non-target labels drop."""
    raw_text = "đau ngực"

    def predictor(text: str):
        return [TokenPrediction("B-AGE", 0, 3, 0.99)]

    ner = ViHealthBERTNER(predictor)
    candidates = ner.predict_windows(
        raw_text,
        "f6",
        [TextWindow(raw_text, 0, len(raw_text), 0, "model")],
    )
    assert candidates == []


def test_unknown_label_map_rejected():
    """Constructor raises ValueError for unsupported label_map values."""
    def predictor(text: str):
        return []

    try:
        ViHealthBERTNER(predictor, label_map="bogus")
    except ValueError as error:
        assert "label_map" in str(error)
    else:
        raise AssertionError("Expected ViHealthBERTNER to reject unknown label_map")


if __name__ == "__main__":
    import inspect
    import sys

    # Discover and run every test_* function defined in this module.
    failures = []
    current_module = sys.modules[__name__]
    test_functions = sorted(
        name
        for name, value in inspect.getmembers(current_module, inspect.isfunction)
        if name.startswith("test_") and value.__module__ == current_module.__name__
    )
    for name in test_functions:
        print(f"  ... running {name}")
        try:
            getattr(current_module, name)()
        except Exception as error:
            print(f"  FAIL  {name}: {type(error).__name__}: {error}")
            failures.append((name, error))
        else:
            print(f"  ok    {name}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        raise SystemExit(1)
    print(f"\nAll {len(test_functions)} tests passed")
