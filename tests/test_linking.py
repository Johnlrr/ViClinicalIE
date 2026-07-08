"""Unit tests for V0 ICD/RxNorm candidate linking."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.linking.candidate_linker import link_mapping_candidates, load_default_linkers
from src.linking.icd10_linker import ICD10Linker
from src.linking.rxnorm_linker import RxNormLinker
from src.models import SpanCandidate
from src.rule_extractors import ENTITY_DIAGNOSIS, ENTITY_DRUG


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIR = ROOT / "data_resources"


def test_icd_exact_common_diagnoses():
    """Common diagnosis terms should map to curated ICD-10 codes."""
    linker = ICD10Linker.from_resources(RESOURCE_DIR)

    assert linker.link("tăng huyết áp").codes == ["I10"]
    assert linker.link("đái tháo đường").codes == ["E11.9"]
    assert linker.link("rung nhĩ").codes == ["I48.9"]

    print("✓ test_icd_exact_common_diagnoses passed")


def test_icd_alias_and_fuzzy():
    """Aliases and orthographic variants should map deterministically."""
    linker = ICD10Linker.from_resources(RESOURCE_DIR)

    assert linker.link("bệnh thận mãn").codes == ["N18.9"]
    assert linker.link("bệnh phổi tắc nghẽn mãn tính").codes == ["J44.9"]
    assert linker.link("nhiễm trùng đường tiết niệu").codes == ["N39.0"]

    print("✓ test_icd_alias_and_fuzzy passed")


def test_rxnorm_exact_strength_examples():
    """ABOUT example drug spans should map to curated RxCUIs."""
    linker = RxNormLinker.from_resources(RESOURCE_DIR)

    assert linker.link("aspirin 81 mg po daily").codes == ["243670"]
    assert linker.link("metoprolol succinate xl 50 mg po daily").codes == ["866436"]
    assert linker.link("clonazepam 0.5 mg po qam:prn").codes == ["197527"]

    print("✓ test_rxnorm_exact_strength_examples passed")


def test_rxnorm_alias_and_ingredient_fallback():
    """Brand aliases and ingredient-only fallbacks should map to RxCUIs."""
    linker = RxNormLinker.from_resources(RESOURCE_DIR)

    assert linker.link("tylenol").codes == ["313782"]
    assert linker.link("coumadin").codes == ["855332"]
    assert linker.link("bactrim").codes == ["198335"]
    assert linker.link("levofloxacin 750mg iv").codes == ["311296"]

    print("✓ test_rxnorm_alias_and_ingredient_fallback passed")


def test_candidate_linker_populates_mapping_candidates():
    """Candidate linker should update only diagnosis/drug mapping candidates."""
    icd_linker, rxnorm_linker = load_default_linkers(RESOURCE_DIR)
    candidates = [
        SpanCandidate(
            file_id="x",
            text="tăng huyết áp",
            start=0,
            end=13,
            type_candidate=ENTITY_DIAGNOSIS,
        ),
        SpanCandidate(
            file_id="x",
            text="tylenol",
            start=20,
            end=27,
            type_candidate=ENTITY_DRUG,
        ),
    ]

    linked, debug_rows = link_mapping_candidates(candidates, icd_linker, rxnorm_linker)

    assert linked[0].mapping_candidates == ["I10"]
    assert linked[1].mapping_candidates == ["313782"]
    assert len(debug_rows) == 2
    assert all(row["codes"] for row in debug_rows)

    print("✓ test_candidate_linker_populates_mapping_candidates passed")


def run_all_tests():
    """Run linking tests without requiring pytest."""
    print("Running linking tests...\n")
    test_icd_exact_common_diagnoses()
    test_icd_alias_and_fuzzy()
    test_rxnorm_exact_strength_examples()
    test_rxnorm_alias_and_ingredient_fallback()
    test_candidate_linker_populates_mapping_candidates()
    print("\n✓✓✓ All linking tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
