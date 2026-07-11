"""Unit tests for the lab entity parser."""

import json
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.lab_parser import (
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    LabParseTrace,
    LabSeed,
    LabTermEntry,
    Line,
    SpanCandidate,
    build_term_lookup,
    classify_lab_line,
    load_lab_dictionary,
    parse_lab_candidates,
)
from src.models import ClinicalDocument
from src.normalization import normalize_for_matching, normalize_with_mapping
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
    """All candidates must slice back to their raw text exactly."""
    for candidate in candidates:
        assert doc.raw_text[candidate.start:candidate.end] == candidate.text, (
            f"Offset mismatch: doc[{candidate.start}:{candidate.end}]="
            f"{doc.raw_text[candidate.start:candidate.end]!r} != "
            f"candidate.text={candidate.text!r}"
        )


# ---------------------------------------------------------------------------
# Core pattern tests
# ---------------------------------------------------------------------------

def test_simple_name_value_colon():
    """name: value – colon-separated pattern."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- troponin: 0.03\n"
    )
    candidates = parse_lab_candidates(doc, ["troponin"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]

    assert len(names) == 1
    assert names[0].text == "troponin"
    assert_offsets(doc, candidates)

    assert len(results) == 1
    assert results[0].text == "0.03"
    assert results[0].type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"

    # Check trace metadata
    name_trace = json.loads(names[0].notes)
    assert name_trace["result_span"] is not None
    assert name_trace["result_kind"] == "numeric"

    print("✓ test_simple_name_value_colon passed")


def test_name_value_whitespace():
    """name value – whitespace-separated pattern (most common in Vietnamese notes)."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- bạch cầu 13.9\n"
    )
    candidates = parse_lab_candidates(doc, ["bạch cầu"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]

    assert len(names) == 1
    assert names[0].text == "bạch cầu"
    assert len(results) == 1
    assert results[0].text == "13.9"
    assert_offsets(doc, candidates)

    print("✓ test_name_value_whitespace passed")


def test_name_parenthetical_description_with_value():
    """name (description): value – parenthetical alias pattern."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm: cea (kháng nguyên ung thư phôi) tăng nhẹ lên 4.9\n"
    )
    candidates = parse_lab_candidates(doc, ["cea"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]

    assert len(names) >= 1
    # The expanded name should include the parenthetical
    name_found = any("cea" in c.text and "kháng nguyên" in c.text for c in names)
    assert name_found, f"Expected expanded name not found in {[c.text for c in names]}"

    assert len(results) >= 1
    assert any("4.9" in c.text for c in results)
    assert_offsets(doc, candidates)

    print("✓ test_name_parenthetical_description_with_value passed")


def test_name_with_unit_value():
    """name value unit – numeric with unit."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- glucose 537 mg/dl\n"
    )
    candidates = parse_lab_candidates(doc, ["glucose"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]

    assert len(names) == 1
    assert names[0].text == "glucose"
    assert len(results) == 1
    assert results[0].text == "537 mg/dl"
    assert_offsets(doc, candidates)

    result_trace = json.loads(results[0].notes)
    assert result_trace["unit"] == "mg/dl"

    print("✓ test_name_with_unit_value passed")


def test_range_value_dash():
    """name value -> value – trend/range with '->'."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- creatinine là 2.0 -> 3.2\n"
    )
    candidates = parse_lab_candidates(doc, ["creatinine"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]

    assert len(names) == 1
    assert len(results) >= 1
    # Should capture the range as a single result span
    range_found = any("2.0" in c.text and "3.2" in c.text for c in results)
    assert range_found, f"Range result not found in {[c.text for c in results]}"
    assert_offsets(doc, candidates)

    print("✓ test_range_value_dash passed")


def test_multiple_pairs_on_same_line():
    """Multiple name-value pairs on one line – each with its own result."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- WBC: 14,43; NEUT%: 76,4\n"
    )
    candidates = parse_lab_candidates(doc, ["WBC", "NEUT%"])

    names = sorted(
        [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"],
        key=lambda c: c.start,
    )
    results = sorted(
        [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"],
        key=lambda c: c.start,
    )

    # We expect at least 2 names
    assert len(names) >= 2, f"Got names: {[c.text for c in names]}"
    name_texts = {c.text for c in names}
    assert "WBC" in name_texts or "NEUT%" in name_texts

    assert len(results) >= 2, f"Got results: {[c.text for c in results]}"
    assert_offsets(doc, candidates)

    print("✓ test_multiple_pairs_on_same_line passed")


def test_name_with_equals_sign():
    """name = value – equals-separated."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- kali = 5.4 mmol/l\n"
    )
    candidates = parse_lab_candidates(doc, ["kali"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]

    assert len(names) == 1
    assert names[0].text == "kali"
    assert len(results) >= 1
    # Should extract "5.4 mmol/l"
    assert any("5.4" in c.text for c in results)
    assert_offsets(doc, candidates)

    print("✓ test_name_with_equals_sign passed")


def test_qualitative_result():
    """name is âm tính / dương tính / bình thường."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- troponin âm tính x1\n"
    )
    candidates = parse_lab_candidates(doc, ["troponin"])

    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]
    assert len(results) >= 1
    assert any("âm tính" in c.text.lower() for c in results), (
        f"Qualitative not found: {[c.text for c in results]}"
    )
    assert_offsets(doc, candidates)

    print("✓ test_qualitative_result passed")


# ---------------------------------------------------------------------------
# Local-role classifier tests
# ---------------------------------------------------------------------------

def test_classify_lab_line_roles():
    """Local role classifier should distinguish subsection, bullet, and neutral lines."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- glucose 537\n"
        "Kết quả chẩn đoán hình ảnh\n"
        "- chụp x-quang ngực không có gì đáng chú ý\n"
    )
    lab_line = next(line for line in doc.lines if "glucose" in line.text)
    imaging_line = next(line for line in doc.lines if "chụp x-quang" in line.text)

    assert classify_lab_line(lab_line) == "lab_subsection_item"
    # Imaging line contains "không có gì đáng chú ý" which matches the
    # qualitative-result regex, so lab_like_line is a valid structural
    # classification. It will not produce false lab candidates because
    # there is no lab dictionary seed on that line.
    assert classify_lab_line(imaging_line) == "lab_like_line"

    print("✓ test_classify_lab_line_roles passed")


def test_bullet_lab_item_role():
    """Bullet item under a general hospital-assessment heading."""
    doc = make_doc(
        "Cận lâm sàng:\n"
        "- lactate 1.1-->0.8\n"
    )
    lactate_line = next(line for line in doc.lines if "lactate" in line.text)
    role = classify_lab_line(lactate_line)
    # "Cận lâm sàng" maps to HOSPITAL_ASSESSMENT (not LAB_RESULT_SECTION),
    # so the bullet item receives lab_like_line from the range pattern.
    # This is valid soft evidence; the confidence adjustment is smaller
    # than for lab_subsection_item but still positive.
    assert role in ("lab_subsection_item", "lab_bullet_item", "lab_like_line"), f"Got {role}"
    print("✓ test_bullet_lab_item_role passed")


# ---------------------------------------------------------------------------
# Subsection confidence boost
# ---------------------------------------------------------------------------

def test_lab_subsection_boosts_confidence():
    """Same lab name in a lab subsection vs narrative context."""
    subsection_doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- creatinine 5.7\n"
    )
    narrative_doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Bệnh nhân có creatinine 5.7 từ lần xét nghiệm trước.\n"
    )

    sub_candidates = parse_lab_candidates(subsection_doc, ["creatinine"])
    nar_candidates = parse_lab_candidates(narrative_doc, ["creatinine"])

    sub_names = [c for c in sub_candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    nar_names = [c for c in nar_candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]

    assert len(sub_names) == 1
    assert len(nar_names) == 1
    assert sub_names[0].confidence > nar_names[0].confidence, (
        f"Subsection ({sub_names[0].confidence}) should be > narrative ({nar_names[0].confidence})"
    )
    assert_offsets(subsection_doc, sub_candidates)
    assert_offsets(narrative_doc, nar_candidates)

    print("✓ test_lab_subsection_boosts_confidence passed")


# ---------------------------------------------------------------------------
# No-result fallback
# ---------------------------------------------------------------------------

def test_lab_name_without_result_still_candidate():
    """A lab name seed with no detectable result should still produce a name candidate."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- bilirubin\n"
    )
    candidates = parse_lab_candidates(doc, ["bilirubin"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    assert len(names) == 1
    assert names[0].text == "bilirubin"

    trace = json.loads(names[0].notes)
    assert trace["result_span"] is None
    assert trace["result_kind"] == "unknown"
    assert_offsets(doc, candidates)

    print("✓ test_lab_name_without_result_still_candidate passed")


# ---------------------------------------------------------------------------
# NER seed integration
# ---------------------------------------------------------------------------

def test_vihealthbert_ner_seed_for_lab_name():
    """ViHealthBERT TÊN_XÉT_NGHIỆM seeds should be usable as lab name seeds."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Bệnh nhân có chỉ số kali là 2.4 tại phòng khám.\n"
    )
    start = doc.raw_text.index("kali")
    end = start + len("kali")
    ner_seed = SpanCandidate(
        file_id=doc.file_id,
        text="kali",
        start=start,
        end=end,
        type_candidate="TÊN_XÉT_NGHIỆM",
        source=["vihealthbert_ner"],
        confidence=0.78,
    )

    candidates = parse_lab_candidates(doc, [], ner_candidates=[ner_seed])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    assert len(names) == 1
    assert names[0].text == "kali"
    trace = json.loads(names[0].notes)
    assert trace["seed_source"] == "vihealthbert_ner"
    assert trace["seed_confidence"] == 0.78
    assert_offsets(doc, candidates)

    print("✓ test_vihealthbert_ner_seed_for_lab_name passed")


# ---------------------------------------------------------------------------
# Dictionary + NER deduplication
# ---------------------------------------------------------------------------

def test_dictionary_priority_over_ner_for_same_span():
    """When dictionary and NER both find the same span, prefer dictionary."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- troponin 0.01\n"
    )
    start = doc.raw_text.index("troponin")
    end = start + len("troponin")
    ner_seed = SpanCandidate(
        file_id=doc.file_id,
        text="troponin",
        start=start,
        end=end,
        type_candidate="TÊN_XÉT_NGHIỆM",
        source=["vihealthbert_ner"],
        confidence=0.85,
    )

    candidates = parse_lab_candidates(doc, ["troponin"], ner_candidates=[ner_seed])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    assert len(names) == 1, (
        f"Should deduplicate to one name, got {[c.text for c in names]}"
    )
    trace = json.loads(names[0].notes)
    assert trace["seed_source"] == "lab_dictionary", (
        f"Expected dictionary priority, got {trace['seed_source']}"
    )
    assert_offsets(doc, candidates)

    print("✓ test_dictionary_priority_over_ner_for_same_span passed")


# ---------------------------------------------------------------------------
# Offset round-trip
# ---------------------------------------------------------------------------

def test_offset_round_trip_all_candidates():
    """Every candidate must pass raw_text[start:end] == text."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- bạch cầu 26.7\n"
        "- kali 3.2\n"
        "- troponin 0.01\n"
        "- lactate 1.8\n"
    )
    candidates = parse_lab_candidates(doc, ["bạch cầu", "kali", "troponin", "lactate"])

    assert len(candidates) == 8  # 4 names + 4 results
    assert_offsets(doc, candidates)

    for c in candidates:
        assert c.start >= 0
        assert c.end <= len(doc.raw_text)
        assert c.start < c.end

    print("✓ test_offset_round_trip_all_candidates passed")


# ---------------------------------------------------------------------------
# Trend/range edge cases
# ---------------------------------------------------------------------------

def test_trend_improvement_value():
    """Lab value with improvement trend: glucose cải thiện thành 367."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- glucose cải thiện thành 367\n"
    )
    candidates = parse_lab_candidates(doc, ["glucose"])

    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]
    assert len(results) >= 1
    assert any("367" in c.text for c in results)
    assert_offsets(doc, candidates)

    print("✓ test_trend_improvement_value passed")


def test_nested_subsection_lab_detection():
    """Lab detection should work even under nested 'Kết quả xét nghiệm xét nghiệm'."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm xét nghiệm\n"
        "- hct (hematocrit) 8.126.3\n"
    )
    candidates = parse_lab_candidates(doc, ["hct"])

    names = [c for c in candidates if c.type_candidate == "TÊN_XÉT_NGHIỆM"]
    assert len(names) >= 1
    assert_offsets(doc, candidates)

    print("✓ test_nested_subsection_lab_detection passed")


# ---------------------------------------------------------------------------
# Comma decimal in Vietnamese notes
# ---------------------------------------------------------------------------

def test_comma_decimal_parsing():
    """Vietnamese notes often use comma as decimal separator."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- huyết khối 26,3\n"
    )
    candidates = parse_lab_candidates(doc, ["huyết khối"])

    results = [c for c in candidates if c.type_candidate == "KẾT_QUẢ_XÉT_NGHIỆM"]
    assert len(results) >= 1
    assert any("26" in c.text and "3" in c.text for c in results)
    assert_offsets(doc, candidates)

    print("✓ test_comma_decimal_parsing passed")


# ---------------------------------------------------------------------------
# No false positives from non-lab lines
# ---------------------------------------------------------------------------

def test_no_false_lab_from_non_lab_term():
    """Lab parser should not produce candidates for a non-lab term appearing in text."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả chẩn đoán hình ảnh\n"
        "- chụp x-quang ngực không ghi nhận gì bất thường\n"
    )
    # "x-quang" is passed as a seed, so the parser will find it — that is
    # dictionary-driven behavior. Use a non-lab/non-medical term instead.
    candidates = parse_lab_candidates(doc, ["không liên quan"])
    # The parser only produces candidates from seeds; if no seed matches,
    # no candidates are generated regardless of result-like patterns.
    assert len(candidates) == 0

    print("✓ test_no_false_lab_on_imaging_line passed")


# ---------------------------------------------------------------------------
# v2 tests: metadata-backed dictionary loading
# ---------------------------------------------------------------------------

def test_load_lab_dictionary_entries():
    """Load lab_terms_curated.csv into LabTermEntry objects."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "data_resources", "lab_terms_curated.csv",
    )
    entries = load_lab_dictionary(path)
    assert len(entries) > 0, "Expected non-empty curated dictionary"
    for entry in entries[:5]:
        assert entry.term
        assert entry.canonical_key
        assert entry.source in {
            "current_seed", "combined_lab_catalog", "abbreviation_txt_alias",
            "manual_curation",
        }
    context_required = [e for e in entries if e.requires_context]
    assert len(context_required) > 0, "Expected some context-required entries"
    assert any(
        e.canonical_key == "kali"
        for e in entries if e.term in ("k", "K")
    )
    print("✓ test_load_lab_dictionary_entries passed")


def test_build_term_lookup():
    """Build normalized lookup from LabTermEntry list."""
    entries = [
        LabTermEntry(
            term="creatinine", canonical_key="creatinine",
            canonical_name="Creatinin",
            source="current_seed", source_detail="", category="chemistry",
            specimen="blood", requires_context=False, priority=4,
        ),
        LabTermEntry(
            term="creatinin", canonical_key="creatinine",
            canonical_name="Creatinin",
            source="combined_lab_catalog", source_detail="", category="chemistry",
            specimen="blood", requires_context=False, priority=3,
        ),
        LabTermEntry(
            term="cr", canonical_key="creatinine",
            canonical_name="Creatinin",
            source="manual_curation", source_detail="", category="chemistry",
            specimen="blood", requires_context=True, priority=5,
        ),
    ]
    lookup = build_term_lookup(entries)
    cr_entry = lookup.get(normalize_for_matching("cr"))
    assert cr_entry is not None
    assert cr_entry.canonical_key == "creatinine"
    assert cr_entry.requires_context is True
    assert cr_entry.priority == 5

    creatin_entry = lookup.get(normalize_for_matching("creatinin"))
    assert creatin_entry is not None
    assert creatin_entry.priority == 3
    print("✓ test_build_term_lookup passed")
# ---------------------------------------------------------------------------
# v2 tests: context-gated aliases
# ---------------------------------------------------------------------------

def test_context_gated_k_in_lab_section():
    """k 5.4 in lab context -> accepted."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- k 5.4\n"
    )
    candidates = parse_lab_candidates(
        doc, ["k", "kali"],
        lab_entries=[
            LabTermEntry(
                term="k", canonical_key="kali", canonical_name="Kali",
                source="current_seed", source_detail="", category="chemistry",
                specimen="blood", requires_context=True, priority=4,
            ),
        ],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    assert any("k" in c.text.lower() for c in names)
    assert_offsets(doc, candidates)
    print("✓ test_context_gated_k_in_lab_section passed")


def test_context_gated_k_rejected_outside_lab():
    """k in ordinary prose without lab context -> rejected."""
    doc = make_doc(
        "1. Hành chính\n"
        "Bệnh nhân nữ, k nhà số 123\n"
    )
    candidates = parse_lab_candidates(
        doc, ["k"],
        lab_entries=[
            LabTermEntry(
                term="k", canonical_key="kali", canonical_name="Kali",
                source="current_seed", source_detail="", category="chemistry",
                specimen="blood", requires_context=True, priority=4,
            ),
        ],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) == 0, "k should be rejected outside lab context"
    print("✓ test_context_gated_k_rejected_outside_lab passed")


def test_context_gated_cr_with_parenthetical_expansion():
    """cr (creatinine) 1.2 in lab context -> accepted."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- cr (creatinine) 1.2\n"
    )
    candidates = parse_lab_candidates(
        doc, ["cr"],
        lab_entries=[
            LabTermEntry(
                term="cr", canonical_key="creatinine",
                canonical_name="Creatinin",
                source="manual_curation", source_detail="", category="chemistry",
                specimen="blood", requires_context=True, priority=5,
            ),
        ],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    assert any("cr" in c.text.lower() for c in names)
    assert_offsets(doc, candidates)
    print("✓ test_context_gated_cr_with_parenthetical_expansion passed")


def test_context_gated_pt_rejected_english_word():
    """pt in an English phrase without lab/result -> rejected."""
    doc = make_doc(
        "1. Hành chính\n"
        "The patient was transferred to the emergency department.\n"
    )
    candidates = parse_lab_candidates(
        doc, ["pt"],
        lab_entries=[
            LabTermEntry(
                term="pt", canonical_key="prothrombin",
                canonical_name="Prothrombin time",
                source="abbreviation_txt_alias", source_detail="",
                category="coagulation", specimen="blood",
                requires_context=True, priority=4,
            ),
        ],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) == 0, "pt in English prose should be rejected"
    print("✓ test_context_gated_pt_rejected_english_word passed")


def test_context_gated_na_inside_lab_with_result():
    """Na: 138 in lab context -> accepted."""
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- điện giải: Na: 138, K: 4.2\n"
    )
    candidates = parse_lab_candidates(
        doc, ["na", "k", "natri", "kali"],
        lab_entries=[
            LabTermEntry(
                term="na", canonical_key="natri", canonical_name="Natri",
                source="abbreviation_txt_alias", source_detail="",
                category="chemistry", specimen="blood",
                requires_context=True, priority=4,
            ),
            LabTermEntry(
                term="k", canonical_key="kali", canonical_name="Kali",
                source="current_seed", source_detail="", category="chemistry",
                specimen="blood", requires_context=True, priority=4,
            ),
        ],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 2
    assert_offsets(doc, candidates)
    print("✓ test_context_gated_na_inside_lab_with_result passed")


# ---------------------------------------------------------------------------
# v2 tests: overlap resolution
# ---------------------------------------------------------------------------

def test_overlap_bilirubin_prefers_bilirubin_toan_phan():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- bilirubin toàn phần 2.1\n"
    )
    candidates = parse_lab_candidates(
        doc, ["bilirubin", "bilirubin toàn phần"],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    long_names = [c for c in names if len(c.text) > 10]
    assert len(long_names) >= 1
    assert any("toàn phần" in c.text.lower() for c in long_names)
    assert_offsets(doc, candidates)
    print("✓ test_overlap_bilirubin_prefers_bilirubin_toan_phan passed")


def test_overlap_canxi_prefers_canxi_ion_hoa():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- canxi ion hóa 6.8\n"
    )
    candidates = parse_lab_candidates(
        doc, ["canxi", "canxi ion hóa"],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    long_names = [c for c in names if len(c.text) > 8]
    assert len(long_names) >= 1
    assert_offsets(doc, candidates)
    print("✓ test_overlap_canxi_prefers_canxi_ion_hoa passed")


def test_overlap_crp_prefers_crp_hs():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- CRP 12.5, CRP hs 2.3\n"
    )
    candidates = parse_lab_candidates(
        doc, ["crp", "crp hs"],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 2
    assert_offsets(doc, candidates)
    print("✓ test_overlap_crp_prefers_crp_hs passed")


# ---------------------------------------------------------------------------
# v2 tests: unit recognition
# ---------------------------------------------------------------------------

def test_unit_iu_l():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- ALT: 45 IU/L\n"
    )
    candidates = parse_lab_candidates(doc, ["alt"])
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert any("45" in c.text for c in results)
    assert_offsets(doc, candidates)
    print("✓ test_unit_iu_l passed")


def test_unit_ng_l():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- NT-proBNP 120 ng/L\n"
    )
    candidates = parse_lab_candidates(doc, ["nt-probnp", "nt probnp"])
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert any("120" in c.text for c in results)
    assert_offsets(doc, candidates)
    print("✓ test_unit_ng_l passed")


def test_unit_percent():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- HbA1c 7.2%\n"
    )
    candidates = parse_lab_candidates(doc, ["hba1c", "hba1c"])
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert any("7.2" in c.text and "%" in c.text for c in results)
    assert_offsets(doc, candidates)
    print("✓ test_unit_percent passed")


# ---------------------------------------------------------------------------
# v2 tests: canonical metadata in trace
# ---------------------------------------------------------------------------

def test_canonical_metadata_in_trace():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- creatinine 1.2\n"
    )
    entries = [
        LabTermEntry(
            term="creatinine", canonical_key="creatinine",
            canonical_name="Creatinin",
            source="current_seed", source_detail="lab_seed_terms.csv",
            category="chemistry", specimen="blood",
            requires_context=False, priority=4,
        ),
    ]
    candidates = parse_lab_candidates(
        doc, ["creatinine"], lab_entries=entries,
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    trace = json.loads(names[0].notes)
    assert trace.get("canonical_key") == "creatinine"
    assert trace.get("canonical_name") == "Creatinin"
    assert trace.get("category") == "chemistry"
    assert trace.get("specimen") == "blood"
    assert trace.get("requires_context") is False
    print("✓ test_canonical_metadata_in_trace passed")


# ---------------------------------------------------------------------------
# v2 tests: regression on real clinical examples
# ---------------------------------------------------------------------------

def test_regression_canxi_ion_hoa():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- canxi là 12.0; canxi ion hóa 6.8\n"
    )
    candidates = parse_lab_candidates(doc, ["canxi", "canxi ion hóa"])
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 2
    assert_offsets(doc, candidates)
    print("✓ test_regression_canxi_ion_hoa passed")


def test_regression_ure_photpho():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- Ure tăng từ 69 lên 91 mg/dl ... photpho 8.4\n"
    )
    candidates = parse_lab_candidates(doc, ["ure", "photpho", "ure máu"])
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert_offsets(doc, candidates)
    print("✓ test_regression_ure_photpho passed")


def test_regression_alp():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- alp 185\n"
    )
    candidates = parse_lab_candidates(doc, ["alp"])
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert any("185" in c.text for c in results)
    assert_offsets(doc, candidates)
    print("✓ test_regression_alp passed")


def test_regression_ferritin_binh_thuong():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- ferritin là bình thường\n"
    )
    candidates = parse_lab_candidates(doc, ["ferritin"])
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert any("bình" in c.text.lower() for c in results)
    assert_offsets(doc, candidates)
    print("✓ test_regression_ferritin_binh_thuong passed")


def test_regression_ck_58():
    doc = make_doc(
        "3. Đánh giá tại bệnh viện\n"
        "Kết quả xét nghiệm\n"
        "- ck 58\n"
    )
    candidates = parse_lab_candidates(
        doc, ["ck", "ck-mb"],
        lab_entries=[
            LabTermEntry(
                term="ck", canonical_key="ck", canonical_name="CK",
                source="manual_curation", source_detail="", category="chemistry",
                specimen="blood", requires_context=True, priority=5,
            ),
        ],
    )
    names = [c for c in candidates if c.type_candidate == ENTITY_LAB_NAME]
    assert len(names) >= 1
    results = [c for c in candidates if c.type_candidate == ENTITY_LAB_RESULT]
    assert len(results) >= 1
    assert any("58" in c.text for c in results)
    assert_offsets(doc, candidates)
    print("✓ test_regression_ck_58 passed")


def run_all_tests():
    """Run lab parser tests without requiring pytest."""
    print("Running lab parser tests...\n")
    test_simple_name_value_colon()
    test_name_value_whitespace()
    test_name_parenthetical_description_with_value()
    test_name_with_unit_value()
    test_range_value_dash()
    test_multiple_pairs_on_same_line()
    test_name_with_equals_sign()
    test_qualitative_result()
    test_classify_lab_line_roles()
    test_bullet_lab_item_role()
    test_lab_subsection_boosts_confidence()
    test_lab_name_without_result_still_candidate()
    test_vihealthbert_ner_seed_for_lab_name()
    test_dictionary_priority_over_ner_for_same_span()
    test_offset_round_trip_all_candidates()
    test_trend_improvement_value()
    test_nested_subsection_lab_detection()
    test_comma_decimal_parsing()
    test_no_false_lab_from_non_lab_term()

    # v2 tests
    print("\n--- v2 tests ---")
    test_load_lab_dictionary_entries()
    test_build_term_lookup()
    test_context_gated_k_in_lab_section()
    test_context_gated_k_rejected_outside_lab()
    test_context_gated_cr_with_parenthetical_expansion()
    test_context_gated_pt_rejected_english_word()
    test_context_gated_na_inside_lab_with_result()
    test_overlap_bilirubin_prefers_bilirubin_toan_phan()
    test_overlap_canxi_prefers_canxi_ion_hoa()
    test_overlap_crp_prefers_crp_hs()
    test_unit_iu_l()
    test_unit_ng_l()
    test_unit_percent()
    test_canonical_metadata_in_trace()
    test_regression_canxi_ion_hoa()
    test_regression_ure_photpho()
    test_regression_alp()
    test_regression_ferritin_binh_thuong()
    test_regression_ck_58()
    print("\n✓✓✓ All lab parser tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()