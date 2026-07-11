"""Unit tests for V0 rule extractors."""

import json
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
    extract_structural_candidates,
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


def test_structural_bullet_harvest_splits_clean_concepts():
    """Dictionary-free bullet fallback should split chronic-disease concepts."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Các bệnh lý mãn tính\n"
        "- bệnh thận mạn, rung nhĩ (AF); suy tim\n"
    )
    candidates = extract_structural_candidates(doc, [])

    diagnosis_texts = [candidate.text for candidate in candidates if candidate.type_candidate == ENTITY_DIAGNOSIS]
    assert diagnosis_texts == ["bệnh thận mạn", "rung nhĩ (AF)", "suy tim"]
    assert all(candidate.source == ["structural_fallback"] for candidate in candidates)
    assert all(candidate.confidence == 0.40 for candidate in candidates)
    assert_offsets(doc, candidates)

    print("✓ test_structural_bullet_harvest_splits_clean_concepts passed")


def test_structural_key_value_harvest_strips_parenthetical_and_caps_long_values():
    """Key-value fallback should harvest capped values and drop final parentheticals."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Lý do nhập viện: đau đầu dữ dội (3 ngày)\n"
        "Triệu chứng hiện tại: đau ngực, khó thở\n"
        "Diễn biến bệnh\n"
        "Vị trí: ngực trái\n"
        "Tóm tắt: một hai ba bốn năm sáu bảy tám chín mười mười một mười hai mười ba\n"
    )
    candidates = extract_structural_candidates(doc, [])

    symptom_texts = [candidate.text for candidate in candidates if candidate.type_candidate == ENTITY_SYMPTOM]
    assert "đau đầu dữ dội" in symptom_texts
    assert "đau ngực" in symptom_texts
    assert "khó thở" in symptom_texts
    assert "ngực trái" not in symptom_texts
    assert not any(text.startswith("một hai ba") for text in symptom_texts)
    assert_offsets(doc, candidates)

    print("✓ test_structural_key_value_harvest_strips_parenthetical_and_caps_long_values passed")


def test_structural_imaging_bullet_and_event_verb_guard():
    """Imaging bullets should be allowed, but event/action bullets skipped."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Chẩn đoán hình ảnh\n"
        "- chụp cắt lớp vi tính mạch máu (ctma)\n"
        "- Được chuyển khoa tim mạch\n"
    )
    candidates = extract_structural_candidates(doc, [])

    lab_name_texts = [candidate.text for candidate in candidates if candidate.type_candidate == ENTITY_LAB_NAME]
    assert lab_name_texts == ["chụp cắt lớp vi tính mạch máu (ctma)"]
    assert_offsets(doc, candidates)

    print("✓ test_structural_imaging_bullet_and_event_verb_guard passed")


def test_structural_current_history_event_bullets_recover_file6_shape():
    """Current-history event bullets should recover non-empty structural symptoms."""
    doc = make_doc(
        "2. Tiền sử bệnh hiện tại\n"
        "Các sự kiện trước khi nhập viện\n"
        "- Ghi nhận trên các siêu âm doppler hai chiều gần đây có hẹp nặng, tỷ số PSV/EDV > 7, vận tốc dòng chảy tăng rõ\n"
        "Tình trạng ngay trước khi nhập viện\n"
        "- Chỉ định can thiệp tái thông động mạch cảnh sau khi đã đánh giá đầy đủ nguy cơ và lợi ích điều trị.\n"
    )
    candidates = extract_structural_candidates(doc, [])

    symptom_texts = [candidate.text for candidate in candidates if candidate.type_candidate == ENTITY_SYMPTOM]
    assert "Ghi nhận trên các siêu âm doppler hai chiều gần đây có hẹp nặng" in symptom_texts
    assert "tỷ số PSV/EDV > 7" in symptom_texts
    assert "vận tốc dòng chảy tăng rõ" in symptom_texts
    assert "Chỉ định can thiệp tái thông động mạch cảnh sau khi đã đánh giá đầy đủ nguy cơ và lợi ích điều trị" in symptom_texts
    assert_offsets(doc, candidates)

    print("✓ test_structural_current_history_event_bullets_recover_file6_shape passed")


def test_trace_metadata_in_diagnosis_candidate_notes():
    """Diagnosis candidates must include rule_id, reliability_tier in notes."""
    doc = make_doc("1. Tiền sử bệnh\nCác bệnh lý mãn tính\n- tăng huyết áp\n")
    candidates = extract_diagnosis_candidates(doc, ["tăng huyết áp"], [])
    candidate = next(c for c in candidates if c.type_candidate == ENTITY_DIAGNOSIS)

    assert candidate.notes is not None and len(candidate.notes) > 0
    trace = json.loads(candidate.notes)
    assert trace["rule_id"] == "diagnosis_dictionary_context_match"
    assert trace["reliability_tier"] == "contextual_dictionary_match"
    assert trace["dictionary_term"] == "tăng huyết áp"
    assert isinstance(trace["raw_span"], list) and len(trace["raw_span"]) == 2
    assert trace["evidence"] == ["diagnosis_dictionary", "section_rule", "diagnosis_context"]

    print("✓ test_trace_metadata_in_diagnosis_candidate_notes passed")


def test_trace_metadata_in_symptom_candidate_notes():
    """Symptom candidates must include rule_id, reliability_tier in notes."""
    doc = make_doc("2. Bệnh sử hiện tại\nLý do nhập viện: đau ngực\n")
    candidates = extract_symptom_candidates(doc, ["đau ngực"])
    candidate = next(c for c in candidates if c.type_candidate == ENTITY_SYMPTOM)

    assert candidate.notes is not None and len(candidate.notes) > 0
    trace = json.loads(candidate.notes)
    assert trace["rule_id"] == "symptom_dictionary_context_match"
    assert trace["reliability_tier"] in ("contextual_dictionary_match", "exact_curated_alias")
    assert trace["dictionary_term"] == "đau ngực"

    print("✓ test_trace_metadata_in_symptom_candidate_notes passed")


def test_trace_metadata_in_drug_candidate_notes():
    """Drug baseline candidates must include rule_id, reliability_tier in notes."""
    doc = make_doc("1. Tiền sử bệnh\nThuốc trước khi nhập viện\n- aspirin 81 mg\n")
    candidates = extract_drug_candidates(doc, ["aspirin"])
    candidate = next((c for c in candidates if c.type_candidate == ENTITY_DRUG), None)
    assert candidate is not None, "No drug candidate produced"

    assert candidate.notes is not None and len(candidate.notes) > 0
    trace = json.loads(candidate.notes)
    assert trace["rule_id"] == "drug_dictionary_baseline"
    assert trace["reliability_tier"] == "contextual_dictionary_match"
    assert trace["dictionary_term"] == "aspirin"

    print("✓ test_trace_metadata_in_drug_candidate_notes passed")


def test_trace_metadata_in_lab_candidate_notes():
    """Lab baseline candidates must include rule_extractor rule_id in notes."""
    doc = make_doc("3. Đánh giá tại bệnh viện\nKết quả xét nghiệm\nWBC:14,43\n")
    candidates = extract_lab_candidates(doc, ["WBC"])
    lab_name = next((c for c in candidates if c.type_candidate == ENTITY_LAB_NAME), None)
    assert lab_name is not None and lab_name.notes is not None

    trace = json.loads(lab_name.notes)
    assert trace["rule_id"] == "lab_dictionary_baseline"
    assert trace["dictionary_term"] == "WBC"

    print("✓ test_trace_metadata_in_lab_candidate_notes passed")


def test_trace_metadata_in_structural_fallback_notes():
    """Structural fallback must include structural_fallback rule_id and tier."""
    doc = make_doc("2. Bệnh sử hiện tại\nLý do nhập viện: đau đầu dữ dội (3 ngày)\n")
    candidates = extract_structural_candidates(doc, [])
    candidate = next((c for c in candidates if c.type_candidate == ENTITY_SYMPTOM), None)
    assert candidate is not None and candidate.notes is not None

    trace = json.loads(candidate.notes)
    assert trace["reliability_tier"] == "structural_fallback"
    assert trace["rule_id"] in ("structural_bullet_harvest", "structural_key_value_harvest")

    print("✓ test_trace_metadata_in_structural_fallback_notes passed")
def run_all_tests():
    """Run rule extractor tests without requiring pytest."""
    print("Running rule extractor tests...\n")
    test_lab_name_and_result_offsets()
    test_drug_span_with_dose_and_typo_recovery()
    test_diagnosis_from_chronic_disease_section()
    test_symptoms_from_admission_and_current_symptoms()
    test_non_target_rejected_but_finding_extracted()
    test_structural_bullet_harvest_splits_clean_concepts()
    test_structural_key_value_harvest_strips_parenthetical_and_caps_long_values()
    test_structural_imaging_bullet_and_event_verb_guard()
    test_structural_current_history_event_bullets_recover_file6_shape()
    test_trace_metadata_in_diagnosis_candidate_notes()
    test_trace_metadata_in_symptom_candidate_notes()
    test_trace_metadata_in_drug_candidate_notes()
    test_trace_metadata_in_lab_candidate_notes()
    test_trace_metadata_in_structural_fallback_notes()
    print("\n✓✓✓ All rule extractor tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
