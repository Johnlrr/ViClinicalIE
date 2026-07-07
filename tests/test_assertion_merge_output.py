"""Unit tests for day-10 assertion, merge, and output helpers."""

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.assertion import add_assertions
from src.merge import merge_candidates
from src.models import ClinicalDocument, SpanCandidate
from src.normalization import normalize_with_mapping
from src.output_writer import create_output_zip, write_output_files
from src.rule_extractors import (
    ENTITY_DIAGNOSIS,
    ENTITY_DRUG,
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_SYMPTOM,
)
from src.section_parser import parse_document_sections
from src.validator import validate_output_artifacts


def make_doc(raw_text: str, file_id: str = "1") -> ClinicalDocument:
    """Create a parsed ClinicalDocument with normalized offset maps."""
    normalized, norm_to_raw, raw_to_norm = normalize_with_mapping(raw_text, for_matching=True)
    doc = ClinicalDocument(
        file_id=file_id,
        raw_text=raw_text,
        normalized_text=normalized,
        norm_to_raw_map=norm_to_raw,
        raw_to_norm_map=raw_to_norm,
    )
    return parse_document_sections(doc)


def make_candidate(doc: ClinicalDocument, text: str, entity_type: str, confidence: float = 0.8) -> SpanCandidate:
    """Create a candidate for the first exact raw occurrence of text."""
    start = doc.raw_text.index(text)
    end = start + len(text)
    line = next(line for line in doc.lines if line.start <= start and end <= line.end)
    return SpanCandidate(
        file_id=doc.file_id,
        text=text,
        start=start,
        end=end,
        type_candidate=entity_type,
        section_type=line.section_type,
        subsection_type=line.subsection_type,
        line_id=line.line_id,
        line_text=line.text,
        source=["test"],
        confidence=confidence,
    )


def test_negation_list_scope():
    """A single negation trigger should cover symptoms in the same list segment."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Triệu chứng hiện tại\n"
        "- Không có sốt, ớn lạnh, nôn, táo bón, ho\n"
    )
    candidates = [
        make_candidate(doc, "sốt", ENTITY_SYMPTOM),
        make_candidate(doc, "ớn lạnh", ENTITY_SYMPTOM),
        make_candidate(doc, "nôn", ENTITY_SYMPTOM),
        make_candidate(doc, "táo bón", ENTITY_SYMPTOM),
        make_candidate(doc, "ho", ENTITY_SYMPTOM),
    ]

    asserted = add_assertions(candidates, {doc.file_id: doc})
    assert all("isNegated" in candidate.assertion_candidates for candidate in asserted)

    print("✓ test_negation_list_scope passed")


def test_negation_trigger_scope():
    """Phủ nhận/không ghi nhận should negate entities after the trigger."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Triệu chứng hiện tại\n"
        "- Phủ nhận đau ngực\n"
        "- không ghi nhận khó thở rõ, đau ngực hoặc ho nhiều\n"
    )
    candidates = [
        make_candidate(doc, "đau ngực", ENTITY_SYMPTOM),
        make_candidate(doc, "khó thở", ENTITY_SYMPTOM),
        SpanCandidate(
            **{
                **make_candidate(doc, "ho", ENTITY_SYMPTOM).__dict__,
                "start": doc.raw_text.rindex("ho"),
                "end": doc.raw_text.rindex("ho") + len("ho"),
                "text": "ho",
            }
        ),
    ]

    asserted = add_assertions(candidates, {doc.file_id: doc})
    assert all("isNegated" in candidate.assertion_candidates for candidate in asserted)

    print("✓ test_negation_trigger_scope passed")


def test_historical_diagnosis_and_drug():
    """Chronic disease and medication history priors should mark historical."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Bệnh lý mãn tính: tăng huyết áp\n"
        "Thuốc trước khi nhập viện\n"
        "- aspirin 81 mg po daily\n"
    )
    candidates = [
        make_candidate(doc, "tăng huyết áp", ENTITY_DIAGNOSIS),
        make_candidate(doc, "aspirin 81 mg po daily", ENTITY_DRUG),
    ]

    asserted = add_assertions(candidates, {doc.file_id: doc})
    assert all("isHistorical" in candidate.assertion_candidates for candidate in asserted)
    assert all(candidate.time_context == "past" for candidate in asserted)

    print("✓ test_historical_diagnosis_and_drug passed")


def test_family_strict_not_narrator():
    """Family assertion should require a family member relation to the entity."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Mẹ bệnh nhân bị đái tháo đường.\n"
        "Người nhà nhận thấy bệnh nhân khó thở.\n"
    )
    family_diagnosis = make_candidate(doc, "đái tháo đường", ENTITY_DIAGNOSIS)
    narrator_symptom = make_candidate(doc, "khó thở", ENTITY_SYMPTOM)

    asserted = add_assertions([family_diagnosis, narrator_symptom], {doc.file_id: doc})
    by_text = {candidate.text: candidate for candidate in asserted}
    assert "isFamily" in by_text["đái tháo đường"].assertion_candidates
    assert "isFamily" not in by_text["khó thở"].assertion_candidates

    print("✓ test_family_strict_not_narrator passed")


def test_merge_priority_and_dedupe():
    """Overlap resolver should keep higher-priority spans and best exact duplicate."""
    doc = make_doc("3. Đánh giá tại bệnh viện\nKết quả xét nghiệm\nWBC:14,43\n")
    lab_result = make_candidate(doc, "14,43", ENTITY_LAB_RESULT, confidence=0.7)
    low_conf_duplicate = make_candidate(doc, "14,43", ENTITY_LAB_RESULT, confidence=0.5)
    symptom_overlap = SpanCandidate(
        **{
            **lab_result.__dict__,
            "text": "WBC:14,43",
            "start": doc.raw_text.index("WBC"),
            "end": doc.raw_text.index("WBC") + len("WBC:14,43"),
            "type_candidate": ENTITY_SYMPTOM,
            "confidence": 0.99,
        }
    )

    merged = merge_candidates([symptom_overlap, low_conf_duplicate, lab_result])
    assert len(merged) == 1
    assert merged[0].type_candidate == ENTITY_LAB_RESULT
    assert merged[0].confidence == 0.7
    assert merged[0].span_status == "accepted"

    print("✓ test_merge_priority_and_dedupe passed")


def test_output_writer_and_validator_schema():
    """Output writer should create submission schema and validator should pass."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Triệu chứng hiện tại\n"
        "- Không có sốt\n"
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "WBC:14,43\n",
    )
    symptom = make_candidate(doc, "sốt", ENTITY_SYMPTOM)
    lab_name = make_candidate(doc, "WBC", ENTITY_LAB_NAME)
    lab_result = make_candidate(doc, "14,43", ENTITY_LAB_RESULT)
    diagnosis = SpanCandidate(
        **{
            **make_candidate(doc, "sốt", ENTITY_SYMPTOM).__dict__,
            "type_candidate": ENTITY_DIAGNOSIS,
            "mapping_candidates": [],
        }
    )
    asserted = add_assertions([symptom, lab_name, lab_result, diagnosis], {doc.file_id: doc})
    merged = merge_candidates(asserted)

    temp_dir = Path(__file__).resolve().parents[1] / ".tmp_test_output"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    try:
        output_dir = temp_dir / "output"
        zip_path = temp_dir / "output.zip"
        write_output_files(merged, [doc], output_dir)
        create_output_zip(output_dir, zip_path)
        report = validate_output_artifacts(output_dir, zip_path, {doc.file_id: doc}, [doc.file_id])
        assert report.ok

        data = json.loads((output_dir / "1.json").read_text(encoding="utf-8"))
        by_type = {entity["type"]: entity for entity in data}
        assert by_type[ENTITY_LAB_NAME]["assertions"] == []
        assert "candidates" not in by_type[ENTITY_LAB_NAME]
        assert by_type[ENTITY_DIAGNOSIS]["candidates"] == []
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    print("✓ test_output_writer_and_validator_schema passed")


def run_all_tests():
    """Run day-10 tests without requiring pytest."""
    print("Running assertion/merge/output tests...\n")
    test_negation_list_scope()
    test_negation_trigger_scope()
    test_historical_diagnosis_and_drug()
    test_family_strict_not_narrator()
    test_merge_priority_and_dedupe()
    test_output_writer_and_validator_schema()
    print("\n✓✓✓ All assertion/merge/output tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
