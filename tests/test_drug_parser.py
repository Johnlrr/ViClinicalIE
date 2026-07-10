"""Unit tests for the offset-safe drug parser."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.drug_parser import (
    DrugComponents,
    classify_medication_line,
    compose_medication_boundary,
    parse_drug_candidates,
)
from src.models import ClinicalDocument, SpanCandidate
from src.normalization import normalize_with_mapping
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
        assert doc.raw_text[candidate.start:candidate.end] == candidate.text


class FakeLinker:
    """Deterministic stand-in for the RxNorm linker."""

    def __init__(self, mapping):
        self.mapping = mapping

    def link(self, text: str, top_k: int = 1):
        from src.linking.common import MappingResult

        key = text.strip().lower().split()[0] if text.strip() else ""
        codes = self.mapping.get(key, [])
        if codes:
            return MappingResult(codes=codes[:top_k], source="rxnorm_exact", confidence=1.0, matched_term=key)
        return MappingResult(codes=[], source="rxnorm_unmapped", confidence=0.0, reason="no_match")


class FakeRxEntry:
    """Tiny RxNorm-like atom for parser seed tests."""

    def __init__(self, string: str, tty: str = "IN"):
        self.string = string
        self.tty = tty


class FakeRxCatalog:
    """Tiny RxNorm-like catalog exposing entries."""

    def __init__(self, terms):
        self._entries: tuple[object, ...] = tuple(FakeRxEntry(term) for term in terms)

    @property
    def entries(self):
        return self._entries



def test_full_medication_mention_with_strength_route_frequency():
    """amlodipine 10 mg po daily should expand to the full mention."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- amlodipine 10 mg po daily\n"
    )
    candidates = parse_drug_candidates(doc, ["amlodipine"])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.text == "amlodipine 10 mg po daily"
    assert candidate.type_candidate == "THUỐC"
    assert_offsets(doc, candidates)
    trace = json.loads(candidate.notes)
    assert trace["components"]["strength"] == ["10 mg"]
    assert trace["components"]["route"] == ["po"]
    assert trace["components"]["frequency"] == ["daily"]

    print("✓ test_full_medication_mention_with_strength_route_frequency passed")


def test_drug_core_without_dose_stays_minimal():
    """A bare mention without dose/route/frequency should not over-extend."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Bệnh nhân từng dùng aspirin trước đây, không rõ liều.\n"
    )
    candidates = parse_drug_candidates(doc, ["aspirin"])

    assert len(candidates) == 1
    assert candidates[0].text == "aspirin"
    assert_offsets(doc, candidates)

    print("✓ test_drug_core_without_dose_stays_minimal passed")


def test_medication_subsection_boosts_confidence_over_narrative():
    """Same drug core should score higher inside a medication subsection."""
    subsection_doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- metoprolol 25mg po bid\n"
    )
    narrative_doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Bệnh nhân có dùng metoprolol 25mg po bid tại nhà.\n"
    )

    subsection_candidates = parse_drug_candidates(subsection_doc, ["metoprolol"])
    narrative_candidates = parse_drug_candidates(narrative_doc, ["metoprolol"])

    assert subsection_candidates[0].confidence > narrative_candidates[0].confidence
    assert_offsets(subsection_doc, subsection_candidates)
    assert_offsets(narrative_doc, narrative_candidates)

    print("✓ test_medication_subsection_boosts_confidence_over_narrative passed")


def test_rxnorm_prelink_raises_confidence_and_populates_candidates():
    """Preliminary RxNorm evidence should raise confidence and fill mapping_candidates."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- warfarin 5mg po daily\n"
    )
    linker = FakeLinker({"warfarin": ["RX000001"]})

    without_linker = parse_drug_candidates(doc, ["warfarin"])
    with_linker = parse_drug_candidates(doc, ["warfarin"], linker=linker)

    assert without_linker[0].mapping_candidates == []
    assert with_linker[0].mapping_candidates == ["RX000001"]
    assert with_linker[0].confidence > without_linker[0].confidence
    assert_offsets(doc, with_linker)

    print("✓ test_rxnorm_prelink_raises_confidence_and_populates_candidates passed")


def test_stops_extension_at_semicolon_and_next_bullet():
    """Boundary composition should not swallow an adjacent drug on the same line."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- aspirin 81 mg po daily; metoprolol 25mg po bid\n"
    )
    candidates = parse_drug_candidates(doc, ["aspirin", "metoprolol"])

    texts = sorted(candidate.text for candidate in candidates)
    assert texts == ["aspirin 81 mg po daily", "metoprolol 25mg po bid"]
    assert_offsets(doc, candidates)

    print("✓ test_stops_extension_at_semicolon_and_next_bullet passed")


def test_typo_recovered_core_still_expands_within_line():
    """Normalized lookup should recover atenololtrong and stay in-line safe."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- Ở nhà bệnh nhân đã sử dụng atenololtrong ngày\n"
    )
    candidates = parse_drug_candidates(doc, ["atenolol trong"])

    assert len(candidates) == 1
    assert candidates[0].text == "atenololtrong"
    assert_offsets(doc, candidates)

    print("✓ test_typo_recovered_core_still_expands_within_line passed")


def test_classify_medication_line_roles():
    """Local role classifier should distinguish subsection, bullet, and neutral lines."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- metoprolol 25mg po bid\n"
        "2. Bệnh sử hiện tại\n"
        "Bệnh nhân dị ứng penicillin.\n"
        "Thời tiết hôm nay rất đẹp.\n"
    )
    drug_line = next(line for line in doc.lines if "metoprolol" in line.text)
    allergy_line = next(line for line in doc.lines if "dị ứng" in line.text)
    neutral_line = next(line for line in doc.lines if "Thời tiết" in line.text)

    assert classify_medication_line(drug_line) == "medication_subsection_item"
    assert classify_medication_line(allergy_line) == "negative_medication_context"
    assert classify_medication_line(neutral_line) == "neutral_line"

    print("✓ test_classify_medication_line_roles passed")


def test_compose_medication_boundary_offset_round_trip():
    """compose_medication_boundary must return offsets that round-trip on raw text."""
    raw_text = "- ibuprofen 400 mg uống mỗi 6 giờ khi cần\n"
    core_start = raw_text.index("ibuprofen")
    core_end = core_start + len("ibuprofen")
    line_end = len(raw_text.rstrip("\n"))

    start, end, components = compose_medication_boundary(raw_text, core_start, core_end, line_end)

    assert raw_text[start:end] == "ibuprofen 400 mg uống mỗi 6 giờ khi cần"
    assert isinstance(components, DrugComponents)
    assert components.strength == ["400 mg"]
    assert components.route == ["uống"]
    assert components.prn == ["khi cần"]

    print("✓ test_compose_medication_boundary_offset_round_trip passed")


def test_no_duplicate_candidates_for_overlapping_terms():
    """Two dictionary terms should not both fire when only one core is present."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- omeprazole 20mg po daily\n"
    )
    candidates = parse_drug_candidates(doc, ["omeprazole"])

    assert len(candidates) == 1
    assert_offsets(doc, candidates)

    print("✓ test_no_duplicate_candidates_for_overlapping_terms passed")


def test_rxnorm_seed_terms_recover_drug_missing_from_curated_dictionary():
    """RxNorm-derived seed terms should recover drugs absent from curated aliases."""
    doc = make_doc(
        "1. Tiền sử bệnh\n"
        "Thuốc trước khi nhập viện\n"
        "- heparin 5000 units iv\n"
    )

    candidates = parse_drug_candidates(doc, [], rxnorm_seed_terms=["heparin"])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.text == "heparin 5000 units iv"
    assert "rxnorm_catalog" in candidate.source
    trace = json.loads(candidate.notes)
    assert trace["seed_source"] == "rxnorm_catalog"
    assert trace["components"]["strength"] == ["5000 units"]
    assert trace["components"]["route"] == ["iv"]
    assert_offsets(doc, candidates)

    print("✓ test_rxnorm_seed_terms_recover_drug_missing_from_curated_dictionary passed")



def test_rxnorm_catalog_filters_to_document_present_ingredient_or_brand_atoms():
    """Full RxNorm-like catalogs should only seed terms present in the document."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Bắt đầu dùng nitroglycerin ngậm khi đau ngực.\n"
    )
    catalog = FakeRxCatalog(["nitroglycerin", "unseenbrand"])

    candidates = parse_drug_candidates(doc, [], rxnorm_seed_catalog=catalog)

    assert len(candidates) == 1
    assert candidates[0].text == "nitroglycerin ngậm"
    assert "rxnorm_catalog" in candidates[0].source
    assert_offsets(doc, candidates)

    print("✓ test_rxnorm_catalog_filters_to_document_present_ingredient_or_brand_atoms passed")



def test_vihealthbert_ner_seed_expands_missing_dictionary_drug():
    """ViHealthBERT THUỐC candidates should be usable as parser core seeds."""
    doc = make_doc(
        "2. Bệnh sử hiện tại\n"
        "Bệnh nhân đã dùng torsemide 20 mg daily tại nhà.\n"
    )
    start = doc.raw_text.index("torsemide")
    end = start + len("torsemide")
    ner_seed = SpanCandidate(
        file_id=doc.file_id,
        text="torsemide",
        start=start,
        end=end,
        type_candidate="THUỐC",
        source=["vihealthbert_ner"],
        confidence=0.81,
    )

    candidates = parse_drug_candidates(doc, [], ner_candidates=[ner_seed])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.text == "torsemide 20 mg daily"
    assert "vihealthbert_ner" in candidate.source
    trace = json.loads(candidate.notes)
    assert trace["seed_source"] == "vihealthbert_ner"
    assert trace["seed_confidence"] == 0.81
    assert_offsets(doc, candidates)

    print("✓ test_vihealthbert_ner_seed_expands_missing_dictionary_drug passed")



def run_all_tests():
    """Run drug parser tests without requiring pytest."""
    print("Running drug parser tests...\n")
    test_full_medication_mention_with_strength_route_frequency()
    test_drug_core_without_dose_stays_minimal()
    test_medication_subsection_boosts_confidence_over_narrative()
    test_rxnorm_prelink_raises_confidence_and_populates_candidates()
    test_stops_extension_at_semicolon_and_next_bullet()
    test_typo_recovered_core_still_expands_within_line()
    test_classify_medication_line_roles()
    test_compose_medication_boundary_offset_round_trip()
    test_no_duplicate_candidates_for_overlapping_terms()
    test_rxnorm_seed_terms_recover_drug_missing_from_curated_dictionary()
    test_rxnorm_catalog_filters_to_document_present_ingredient_or_brand_atoms()
    test_vihealthbert_ner_seed_expands_missing_dictionary_drug()
    print("\n✓✓✓ All drug parser tests passed! ✓✓✓")


if __name__ == "__main__":
    run_all_tests()
