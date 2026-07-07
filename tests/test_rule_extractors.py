"""Unit tests for V0 rule extractors."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.models import ClinicalDocument
from src.normalization import normalize_with_mapping
from src.rule_extractors import (
    ENTITY_DIAGNOSIS,
    ENTITY_DRUG,
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_NON_TARGET,
    ENTITY_SYMPTOM,
    extract_diagnosis_candidates,
    extract_drug_candidates,
    extract_lab_candidates,
    extract_symptom_candidates,
    reject_non_target_candidates,
)
from src.section_parser import parse_document_sections


def make_doc(raw_text: str) -> ClinicalDocument:
    """Create a parsed ClinicalDocument with normalized offset maps."""
    normalized, norm_to_raw, raw_to_norm = normalize_with_mapping(raw_text, for_matching=True)
    doc = ClinicalDocument(
        file_id="x",
        raw_text=raw_text,
        normalized_text=normalized,
        norm_to_raw_map=norm_to_raw,
        raw_to_norm_map=raw_to_norm,
    )
    return parse_document_sections(doc)


def assert_offsets(doc: ClinicalDocument, candidates):
    """All candidates must slice back to their raw text."""
    for candidate in candidates:
        assert doc.raw_text[candidate.start:candidate.end] == candidate.text


def test_lab_name_and_result_offsets():
    """WBC:14,43 should produce lab name and result candidates."""
    doc = make_doc("3. Đánh giá tại bệnh viện\nKết quả xét nghiệm\nWBC:14,43\n")
    candidates = extract_lab_candidates(doc, ["WBC"])

    assert any(candidate.type_candidate == ENTITY_LAB_NAME and candidate.text == "WBC" for candidate in candidates)
    assert any(candidate.type_candidate == ENTITY_LAB_RESULT and candidate.text == "14,43" for candidate in candidates)
    assert_offsets(doc, candidates)

    print("✓ test_lab_name_and_result_offsets passed")


def test_drug_span_with_dose_and_typo_recovery():
    """Drug extractor should keep dose text and recover atenololtrong."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- metoprolol 25mg po bid\n"
        "- Ở nhà bệnh nhân đã sử dụng atenololtrong ngày\n"
    )
    candidates = extract_drug_candidates(doc, ["metoprolol", "atenolol trong"])

    assert any(candidate.type_candidate == ENTITY_DRUG and candidate.text == "metoprolol 25mg po bid" for candidate in candidates)
    assert any(candidate.type_candidate == ENTITY_DRUG and candidate.text == "atenololtrong" for candidate in candidates)
    assert_offsets(doc, candidates)

    print("✓ test_drug_span_with_dose_and_typo_recovery passed")


def test_diagnosis_from_chronic_disease_section():
    """Chronic disease bullet should produce a diagnosis candidate."""
    doc = make_doc("1. Tiền sử bệnh\nCác bệnh lý mãn tính\n- tăng huyết áp\n")
    candidates = extract_diagnosis_candidates(doc, ["tăng huyết áp"], [])

    diagnosis = next(candidate for candidate in candidates if candidate.type_candidate == ENTITY_DIAGNOSIS)
    assert diagnosis.text == "tăng huyết áp"
    assert diagnosis.section_type == "PAST_HISTORY"
    assert diagnosis.subsection_type == "CHRONIC_DISEASES"
    assert_offsets(doc, candidates)

    print("✓ test_diagnosis_from_chronic_disease_section passed")


def test_symptoms_from_admission_and_current_symptoms():
    """Symptoms should be extracted from admission reason and symptom bullets."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Lý do nhập viện: đau ngực\n"
        "Triệu chứng hiện tại\n"
        "- khó thở khi gắng sức\n"
    )
    candidates = extract_symptom_candidates(doc, ["đau ngực", "khó thở"])

    assert any(candidate.type_candidate == ENTITY_SYMPTOM and candidate.text == "đau ngực" for candidate in candidates)
    assert any(candidate.type_candidate == ENTITY_SYMPTOM and candidate.text == "khó thở khi gắng sức" for candidate in candidates)
    assert_offsets(doc, candidates)

    print("✓ test_symptoms_from_admission_and_current_symptoms passed")


def test_non_target_rejected_but_finding_extracted():
    """Imaging method should be rejected while the finding after trigger is extracted."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả chẩn đoán hình ảnh: chụp x-quang ngực cho thấy sỏi ống mật chủ\n"
    )
    rejected = reject_non_target_candidates(doc, ["chụp x-quang"])
    diagnoses = extract_diagnosis_candidates(doc, ["sỏi ống mật chủ"], ["chụp x-quang"])

    assert any(candidate.type_candidate == ENTITY_NON_TARGET and not candidate.should_output for candidate in rejected)
    assert any(candidate.type_candidate == ENTITY_DIAGNOSIS and candidate.text == "sỏi ống mật chủ" for candidate in diagnoses)
    assert_offsets(doc, rejected + diagnoses)

    print("✓ test_non_target_rejected_but_finding_extracted passed")


def run_all_tests():
    """Run rule extractor tests without requiring pytest."""
    print("Running rule extractor tests...\n")
    test_lab_name_and_result_offsets()
    test_drug_span_with_dose_and_typo_recovery()
    test_diagnosis_from_chronic_disease_section()
    test_symptoms_from_admission_and_current_symptoms()
    test_non_target_rejected_but_finding_extracted()
    print("\n✓✓✓ All rule extractor tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
