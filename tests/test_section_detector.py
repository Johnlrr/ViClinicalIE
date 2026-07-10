from __future__ import annotations

from src.data_types import Chunk
from src.preprocess.chunker import chunk_text
from src.section.section_detector import SECTION_LABELS, SectionDetector, detect_sections


PATTERNS = {
    "PRE_ADMISSION_MEDICATION": ["thuốc trước khi nhập viện"],
    "LAB_RESULT": ["kết quả xét nghiệm", "xét nghiệm"],
    "CURRENT_SYMPTOM": ["triệu chứng hiện tại"],
    "DIAGNOSIS_FINDING": ["chẩn đoán"],
}


def test_heading_detection_maps_medication_section() -> None:
    detector = SectionDetector(PATTERNS)
    match = detector.detect_chunk_section(Chunk(text="Thuốc trước khi nhập viện", start=0, end=24))

    assert match is not None
    assert match.label == "PRE_ADMISSION_MEDICATION"
    assert match.confidence >= 0.9


def test_carry_forward_behavior_for_lab_result() -> None:
    raw = "Kết quả xét nghiệm:\nWBC 14.5\nCreatinine 2.0"
    chunks = chunk_text(raw)
    sectioned = detect_sections(chunks, PATTERNS)

    assert [chunk.section for chunk in sectioned] == ["LAB_RESULT", "LAB_RESULT", "LAB_RESULT"]
    assert sectioned[1].section_source == "carry_forward"
    for chunk in sectioned:
        assert raw[chunk.start:chunk.end] == chunk.text


def test_inline_heading_detection() -> None:
    detector = SectionDetector(PATTERNS)
    chunk = Chunk(text="Triệu chứng hiện tại: đau ngực, khó thở", start=0, end=39)
    match = detector.detect_chunk_section(chunk)

    assert match is not None
    assert match.label == "CURRENT_SYMPTOM"
    assert "inline" in match.source


def test_unknown_fallback_before_any_heading() -> None:
    chunks = [Chunk(text="Bệnh nhân nhập viện sáng nay", start=0, end=27)]
    sectioned = detect_sections(chunks, PATTERNS)

    assert sectioned[0].section == "UNKNOWN"
    assert sectioned[0].section_source == "default"


def test_section_labels_are_valid_after_detection() -> None:
    raw = "Chẩn đoán:\nViêm phổi\nKết quả xét nghiệm:\nWBC 14.5"
    chunks = chunk_text(raw)
    sectioned = detect_sections(chunks, PATTERNS)

    assert sectioned
    for chunk in sectioned:
        assert chunk.section in SECTION_LABELS
        assert raw[chunk.start:chunk.end] == chunk.text
