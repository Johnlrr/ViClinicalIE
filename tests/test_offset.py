"""Unit tests for offset mapper and validation."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.offset_mapper import OffsetMapper, create_offset_mapper
from src.normalization import normalize_for_matching


def test_exact_match():
    """Test exact offset match without normalization."""
    raw_text = "Bệnh nhân có tiền sử tăng huyết áp"
    normalized = raw_text.lower()
    
    mapper = create_offset_mapper(raw_text, normalized)
    
    # Test valid span
    assert mapper.validate_span("tiền sử", 13, 20, use_raw=True)
    assert mapper.validate_span("tăng huyết áp", 21, 34, use_raw=True)
    
    print("✓ test_exact_match passed")


def test_diacritic_handling():
    """Test Vietnamese diacritics are preserved."""
    raw_text = "đái tháo đường"
    normalized = raw_text.lower()
    
    mapper = create_offset_mapper(raw_text, normalized)
    
    # Find in raw should work
    result = mapper.find_in_raw("đái tháo đường")
    assert result == (0, 14)
    
    # Validate
    assert mapper.validate_span("đái tháo đường", 0, 14, use_raw=True)
    
    print("✓ test_diacritic_handling passed")


def test_typo_compound_words():
    """Test handling of compound words with missing spaces."""
    raw_text = "bệnh nhân đã sử dụng atenololtrong ngày"
    normalized = normalize_for_matching(raw_text)
    
    mapper = create_offset_mapper(raw_text, normalized)
    
    # The compound word should still be findable
    result = mapper.find_in_raw("atenololtrong", start_hint=20)
    assert result is not None
    assert mapper.validate_span("atenololtrong", result[0], result[1], use_raw=True)
    
    print("✓ test_typo_compound_words passed")


def test_spacing_issues():
    """Test handling of extra spaces."""
    raw_text = "cảm giác  khó chịu"  # Two spaces
    
    mapper = create_offset_mapper(raw_text, raw_text)
    
    # Find each component
    result1 = mapper.find_in_raw("cảm giác")
    assert result1 == (0, 8)
    
    result2 = mapper.find_in_raw("khó chịu")
    assert result2 is not None
    
    print("✓ test_spacing_issues passed")


def test_recover_from_normalized_typo_fix():
    """Test recovering a raw span from a normalized typo-expanded match."""
    raw_text = "bệnh nhân đã sử dụng atenololtrong ngày"
    normalized = normalize_for_matching(raw_text)

    mapper = create_offset_mapper(raw_text, normalized)
    norm_start = normalized.index("atenolol trong")
    norm_end = norm_start + len("atenolol trong")

    raw_span = mapper.recover_raw_span_from_normalized_match(norm_start, norm_end)
    assert raw_span is not None
    start, end = raw_span
    assert raw_text[start:end] == "atenololtrong"

    print("✓ test_recover_from_normalized_typo_fix passed")


def test_recover_from_normalized_whitespace_collapse():
    """Test recovering raw text when normalized matching collapses whitespace."""
    raw_text = "cảm giác  khó chịu"
    normalized = normalize_for_matching(raw_text)

    mapper = create_offset_mapper(raw_text, normalized)
    norm_start = normalized.index("cảm giác khó chịu")
    norm_end = norm_start + len("cảm giác khó chịu")

    raw_span = mapper.recover_raw_span_from_normalized_match(norm_start, norm_end)
    assert raw_span is not None
    start, end = raw_span
    assert raw_text[start:end] == "cảm giác  khó chịu"

    print("✓ test_recover_from_normalized_whitespace_collapse passed")


def test_case_insensitive_finding():
    """Test case-insensitive finding."""
    raw_text = "Kết quả CHẨN ĐOÁN hình ảnh"
    normalized = raw_text.lower()
    
    mapper = create_offset_mapper(raw_text, normalized)
    
    # Find with different case
    result = mapper.find_in_raw("chẩn đoán", start_hint=8)
    assert result is not None
    
    # The actual extraction should match raw case
    start, end = result
    extracted = raw_text[start:end]
    assert extracted == "CHẨN ĐOÁN"
    
    print("✓ test_case_insensitive_finding passed")


def test_multiple_occurrences():
    """Test finding multiple occurrences."""
    raw_text = "táo bón, không táo bón, không có táo bón"
    
    mapper = create_offset_mapper(raw_text, raw_text)
    
    results = mapper.find_all_in_raw("táo bón", case_sensitive=False)
    assert len(results) == 3
    
    # Verify each occurrence
    for start, end in results:
        assert mapper.validate_span("táo bón", start, end, use_raw=True)
    
    print("✓ test_multiple_occurrences passed")


def test_mixed_english_vietnamese():
    """Test mixed English/Vietnamese text."""
    raw_text = "metoprolol 25mg po bid"
    
    mapper = create_offset_mapper(raw_text, raw_text)
    
    # Find drug name
    result = mapper.find_in_raw("metoprolol")
    assert result == (0, 10)
    
    # Find dosage
    result = mapper.find_in_raw("25mg")
    assert result == (11, 15)
    
    print("✓ test_mixed_english_vietnamese passed")


def test_number_unit_patterns():
    """Test finding numbers with units."""
    raw_text = "levofloxacin 750mg iv, glucose 316"
    
    mapper = create_offset_mapper(raw_text, raw_text)
    
    # Find with number
    result = mapper.find_in_raw("750mg")
    assert result == (13, 18)
    
    result = mapper.find_in_raw("316")
    assert result == (31, 34)
    
    # Validate
    assert mapper.validate_span("750mg", 13, 18, use_raw=True)
    assert mapper.validate_span("316", 31, 34, use_raw=True)
    
    print("✓ test_number_unit_patterns passed")


def test_boundary_validation():
    """Test offset boundary validation."""
    raw_text = "test string"
    
    mapper = create_offset_mapper(raw_text, raw_text)
    
    # Invalid bounds should return False
    assert not mapper.validate_span("test", -1, 4, use_raw=True)  # negative start
    assert not mapper.validate_span("test", 0, 100, use_raw=True)  # end beyond text
    assert not mapper.validate_span("test", 5, 4, use_raw=True)  # start >= end
    
    print("✓ test_boundary_validation passed")


def run_all_tests():
    """Run all offset tests."""
    print("Running offset validation tests...\n")
    
    test_exact_match()
    test_diacritic_handling()
    test_typo_compound_words()
    test_spacing_issues()
    test_recover_from_normalized_typo_fix()
    test_recover_from_normalized_whitespace_collapse()
    test_case_insensitive_finding()
    test_multiple_occurrences()
    test_mixed_english_vietnamese()
    test_number_unit_patterns()
    test_boundary_validation()
    
    print("\n✓✓✓ All offset tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
