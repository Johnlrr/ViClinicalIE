"""Unit tests for section and line parsing."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import ClinicalDocument
from src.section_parser import parse_document_sections


def test_current_history_not_past_history():
    """The longer current-history alias must beat the shorter past-history alias."""
    raw_text = (
        "1. Tiền sử bệnh\n"
        "- tăng huyết áp\n\n"
        "2. Tiền sử bệnh hiện tại\n"
        "Lý do nhập viện: đau ngực\n"
    )
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    section_types = [section.section_type for section in doc.sections]
    assert section_types[0] == "PAST_HISTORY"
    assert "CURRENT_HISTORY" in section_types

    current_header = next(section for section in doc.sections if section.section_type == "CURRENT_HISTORY")
    assert doc.raw_text[current_header.start:current_header.end] == "Tiền sử bệnh hiện tại"

    print("✓ test_current_history_not_past_history passed")


def test_key_value_header_is_clean():
    """A key-value line should classify by key without storing value as alias text."""
    raw_text = "3. Đánh giá tại bệnh viện\nKết quả xét nghiệm: troponin là 0.10\n"
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    lab_section = next(section for section in doc.sections if section.section_type == "LAB_RESULT_SECTION")
    assert lab_section.text == "Kết quả xét nghiệm"
    assert doc.raw_text[lab_section.start:lab_section.end] == "Kết quả xét nghiệm"

    lab_line = next(line for line in doc.lines if line.key == "Kết quả xét nghiệm")
    assert lab_line.line_kind == "key_value"
    assert lab_line.value == "troponin là 0.10"
    assert lab_line.subsection_type == "LAB_RESULT_SECTION"

    print("✓ test_key_value_header_is_clean passed")


def test_chronic_diseases_is_subsection_of_past_history():
    """Chronic disease headers should not masquerade as a top-level past section."""
    raw_text = "1. Tiền sử bệnh\nCác bệnh lý mãn tính\n- tăng huyết áp\n"
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    chronic_section = next(section for section in doc.sections if section.section_type == "CHRONIC_DISEASES")
    assert chronic_section.level == 2
    assert chronic_section.parent_section_type == "PAST_HISTORY"

    chronic_line = next(line for line in doc.lines if line.text == "Các bệnh lý mãn tính")
    assert chronic_line.section_type == "PAST_HISTORY"
    assert chronic_line.subsection_type == "CHRONIC_DISEASES"

    print("✓ test_chronic_diseases_is_subsection_of_past_history passed")


def test_orphan_admission_reason_infers_current_history():
    """A note starting with admission reason should still get a useful main parent."""
    raw_text = "Lý do nhập viện: đau bụng\nBệnh nhân đau 2 ngày.\n"
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    admission_section = doc.sections[0]
    assert admission_section.section_type == "ADMISSION_REASON"
    assert admission_section.parent_section_type == "CURRENT_HISTORY"
    assert doc.lines[0].section_type == "CURRENT_HISTORY"
    assert doc.lines[0].subsection_type == "ADMISSION_REASON"

    print("✓ test_orphan_admission_reason_infers_current_history passed")


def test_orphan_medication_history_infers_past_history():
    """A medication history line before any main header should attach to past history."""
    raw_text = "Thuốc trước khi nhập viện: aspirin 81 mg\n"
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    med_section = doc.sections[0]
    assert med_section.section_type == "MEDICATION_HISTORY"
    assert med_section.parent_section_type == "PAST_HISTORY"
    assert doc.lines[0].section_type == "PAST_HISTORY"
    assert doc.lines[0].subsection_type == "MEDICATION_HISTORY"

    print("✓ test_orphan_medication_history_infers_past_history passed")


def test_glued_header_is_trimmed():
    """A header glued to content should store only the header span."""
    raw_text = "2. Tiền sử bệnh hiện tạiBệnh nhân nhập viện vì đau bụng.\n"
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    section = doc.sections[0]
    assert section.section_type == "CURRENT_HISTORY"
    assert section.text == "Tiền sử bệnh hiện tại"
    assert doc.raw_text[section.start:section.end] == "Tiền sử bệnh hiện tại"

    print("✓ test_glued_header_is_trimmed passed")


def test_line_offsets_are_raw_exact():
    """Every line offset should slice back to the original raw line text."""
    raw_text = "1. Tiền sử bệnh\r\n    - aspirin 81 mg\r\n"
    doc = parse_document_sections(ClinicalDocument(file_id="x", raw_text=raw_text))

    for line in doc.lines:
        assert doc.raw_text[line.start:line.end] == line.text

    print("✓ test_line_offsets_are_raw_exact passed")


def run_all_tests():
    """Run section parser tests without requiring pytest."""
    print("Running section parser tests...\n")
    test_current_history_not_past_history()
    test_key_value_header_is_clean()
    test_chronic_diseases_is_subsection_of_past_history()
    test_orphan_admission_reason_infers_current_history()
    test_orphan_medication_history_infers_past_history()
    test_glued_header_is_trimmed()
    test_line_offsets_are_raw_exact()
    print("\n✓✓✓ All section parser tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
