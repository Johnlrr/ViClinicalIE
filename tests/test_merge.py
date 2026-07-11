"""Integration & unit tests for source-aware merge/resolver.

Covers Section 13.3 of ``2_dictionary_rules.md`` —
NER-parser-rule overlap, source merging, structural fallback deprioritization.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.merge import (
    SOURCE_RELIABILITY_RANK,
    _merge_sources,
    _source_rank,
    merge_candidates,
)
from src.models import SpanCandidate


def _candidate(file_id, text, start, end, entity_type, source, confidence, notes=""):
    return SpanCandidate(
        file_id=file_id, text=text, start=start, end=end,
        type_candidate=entity_type, source=source, confidence=confidence,
        should_output=True, span_status="candidate", notes=notes,
        line_id=1, line_text="", section_type="", subsection_type="",
        left_context="", right_context="",
    )


# =============================================================================
# Source-rank tests
# =============================================================================


def test_source_rank_parser_is_highest():
    drug_parser_cand = _candidate("1", "aspirin", 10, 17, "THUỐC", ["drug_parser"], 0.95)
    dict_cand = _candidate("1", "aspirin", 10, 17, "THUỐC", ["drug_dictionary"], 0.80)
    assert _source_rank(drug_parser_cand) < _source_rank(dict_cand)
    print("test_source_rank_parser_is_highest: OK")


def test_source_rank_structural_is_lowest():
    fallback = _candidate("1", "x", 0, 5, "TRIỆU_CHỨNG", ["structural_fallback"], 0.40)
    assert _source_rank(fallback) >= 20
    print("test_source_rank_structural_is_lowest: OK")


def test_source_rank_reads_trace_tier():
    trace = json.dumps({"reliability_tier": "specialized_parser"})
    cand = _candidate("1", "x", 0, 10, "THUỐC", ["drug_dictionary"], 0.80, notes=trace)
    assert _source_rank(cand) == 1
    print("test_source_rank_reads_trace_tier: OK")


# =============================================================================
# Merge + dedupe tests (Section 13.3)
# =============================================================================


def test_same_span_same_type_merge_sources():
    ner = _candidate("1", "đau ngực", 20, 30, "TRIỆU_CHỨNG", ["vihealthbert_ner"], 0.92,
                     notes=json.dumps({"reliability_tier": "semantic_ner"}))
    dct = _candidate("1", "đau ngực", 20, 30, "TRIỆU_CHỨNG", ["symptom_dictionary"], 0.84,
                     notes=json.dumps({"reliability_tier": "contextual_dictionary_match"}))
    merged = merge_candidates([ner, dct])
    assert len(merged) == 1
    assert set(merged[0].source) >= {"vihealthbert_ner", "symptom_dictionary"}
    assert merged[0].confidence >= 0.90
    print("test_same_span_same_type_merge_sources: OK")


def test_ner_longer_boundary_keep_ner_over_dict():
    dct = _candidate("1", "đái tháo đường", 50, 64, "CHẨN_ĐOÁN", ["diagnosis_dictionary"], 0.72)
    ner = _candidate("1", "đái tháo đường type 2", 50, 72, "CHẨN_ĐOÁN", ["vihealthbert_ner"], 0.88)
    merged = merge_candidates([dct, ner])
    assert len(merged) == 1
    assert merged[0].text == "đái tháo đường type 2"
    print("test_ner_longer_boundary_keep_ner_over_dict: OK")


def test_rule_drug_baseline_vs_drug_parser_same_span_merge():
    rule = _candidate("1", "aspirin 81 mg", 10, 23, "THUỐC",
                      ["drug_dictionary", "dose_parser"], 0.78,
                      notes=json.dumps({"rule_id": "drug_dictionary_baseline",
                                        "reliability_tier": "exact_curated_alias"}))
    parser = _candidate("1", "aspirin 81 mg", 10, 23, "THUỐC",
                        ["drug_parser", "drug_dictionary", "boundary_composition", "dose_parser"],
                        0.95,
                        notes=json.dumps({"reliability_tier": "specialized_parser",
                                          "DrugParseTrace": {"dose": "81 mg"}}))
    merged = merge_candidates([rule, parser])
    assert len(merged) == 1
    assert "drug_parser" in merged[0].source
    assert "DrugParseTrace" in merged[0].notes
    print("test_rule_drug_baseline_vs_drug_parser_same_span_merge: OK")


def test_rule_lab_baseline_vs_lab_parser_merge():
    rule = _candidate("1", "WBC", 40, 43, "TÊN_XÉT_NGHIỆM", ["lab_dictionary", "lab_regex"], 0.86)
    parser = _candidate("1", "WBC", 40, 43, "TÊN_XÉT_NGHIỆM",
                        ["lab_parser", "lab_dictionary"], 0.92,
                        notes=json.dumps({"LabParseTrace": {"name": "WBC"}}))
    merged = merge_candidates([rule, parser])
    assert len(merged) == 1
    assert "lab_parser" in merged[0].source
    print("test_rule_lab_baseline_vs_lab_parser_merge: OK")

def test_structural_fallback_removed_when_parser_better():
    fallback = _candidate("1", "aspirin", 100, 107, "THUỐC", ["structural_fallback"], 0.40,
                          notes=json.dumps({"reliability_tier": "structural_fallback"}))
    parser = _candidate("1", "aspirin 81 mg po daily", 100, 120, "THUỐC",
                        ["drug_parser", "drug_dictionary", "boundary_composition"], 0.95)
    merged = merge_candidates([fallback, parser])
    assert len(merged) == 1
    assert merged[0].text == "aspirin 81 mg po daily"
    print("test_structural_fallback_removed_when_parser_better: OK")


def test_noruleid_candidates_still_merge():
    a = _candidate("1", "test", 0, 10, "THUỐC", ["drug_dictionary"], 0.70)
    b = _candidate("1", "test", 0, 10, "THUỐC", ["drug_parser"], 0.95)
    merged = merge_candidates([a, b])
    assert len(merged) == 1
    print("test_noruleid_candidates_still_merge: OK")


def test_nonoutput_candidates_skipped():
    ok = _candidate("1", "valid", 0, 5, "TRIỆU_CHỨNG", ["symptom_dictionary"], 0.80)
    reject = SpanCandidate(
        file_id="1", text="xray", start=100, end=104, type_candidate="NON_TARGET",
        source=["non_target_dictionary"], confidence=0.90, should_output=False,
        span_status="rejected", reject_reason="imaging_method",
        line_id=0, line_text="", section_type="", subsection_type="",
        left_context="", right_context="", notes="",
    )
    merged = merge_candidates([ok, reject])
    assert len(merged) == 1
    assert merged[0].text == "valid"
    print("test_nonoutput_candidates_skipped: OK")


def test_merge_sources_deduplicates_tags():
    keep = _candidate("1", "x", 0, 5, "THUỐC", ["drug_parser", "drug_dictionary"], 0.90)
    other = _candidate("1", "x", 0, 5, "THUỐC", ["drug_parser", "drug_dictionary", "boundary_composition"], 0.85)
    merged = _merge_sources(keep, other)
    assert merged.source == ["drug_parser", "drug_dictionary", "boundary_composition"]
    print("test_merge_sources_deduplicates_tags: OK")


def test_merge_sources_prefers_stronger_trace():
    keep = _candidate("1", "x", 0, 5, "THUỐC", ["drug_dictionary"], 0.80,
                      notes=json.dumps({"reliability_tier": "exact_curated_alias"}))
    other = _candidate("1", "x", 0, 5, "THUỐC", ["drug_parser"], 0.95,
                       notes=json.dumps({"reliability_tier": "specialized_parser", "DrugParseTrace": {}}))
    merged = _merge_sources(keep, other)
    assert "DrugParseTrace" in merged.notes
    assert merged.confidence > 0.89
    print("test_merge_sources_prefers_stronger_trace: OK")


# =============================================================================
# Runner
# =============================================================================


if __name__ == "__main__":
    print("Running merge tests...\n")
    test_source_rank_parser_is_highest()
    test_source_rank_structural_is_lowest()
    test_source_rank_reads_trace_tier()
    test_same_span_same_type_merge_sources()
    test_ner_longer_boundary_keep_ner_over_dict()
    test_rule_drug_baseline_vs_drug_parser_same_span_merge()
    test_rule_lab_baseline_vs_lab_parser_merge()
    test_structural_fallback_removed_when_parser_better()
    test_noruleid_candidates_still_merge()
    test_nonoutput_candidates_skipped()
    test_merge_sources_deduplicates_tags()
    test_merge_sources_prefers_stronger_trace()
    print("\n✓✓✓ All merge tests passed! ✓✓✓")
