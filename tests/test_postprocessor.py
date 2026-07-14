from __future__ import annotations

from src.data_types import FinalEntity
from src.postprocess import Postprocessor


def _entity(raw_text: str, text: str, entity_type: str, **kwargs) -> FinalEntity:
    start = raw_text.index(text)
    return FinalEntity(text=text, start=start, end=start + len(text), type=entity_type, **kwargs)


def test_postprocessor_end_to_end_trims_keeps_and_drops() -> None:
    raw_text = "Không sốt. Thuốc trước nhập viện: metoprolol 25mg po bid. Một ngày uống cà phê có caffeine."
    entities = [
        _entity(raw_text, "Không sốt", "TRIỆU_CHỨNG"),
        _entity(
            raw_text,
            "metoprolol 25mg po bid",
            "THUỐC",
            candidates=["clinical_25", "clinical_25"],
            provenance={"rxnorm_linking": {"parsed": {"strength_value": 25.0, "route": "po", "frequency": "bid"}}},
        ),
        _entity(raw_text, "caffeine", "THUỐC", candidates=["1886"], provenance={"rxnorm_linking": {"parsed": {}}}),
    ]

    result = Postprocessor({}).process(entities, raw_text)

    texts = [entity.text for entity in result.entities]
    assert texts == ["sốt", "metoprolol 25mg po bid"]
    fever = result.entities[0]
    drug = result.entities[1]
    assert fever.assertions == ["isNegated"]
    assert drug.candidates == ["clinical_25"]
    assert result.report.entities_trimmed == 1
    assert result.report.entities_dropped == 1
    assert result.report.offset_errors == []
    for entity in result.entities:
        assert raw_text[entity.start : entity.end] == entity.text


def test_postprocessor_removes_exact_duplicate_and_wrong_type_candidates() -> None:
    raw_text = "đau đầu"
    first = FinalEntity(text=raw_text, start=0, end=len(raw_text), type="TRIỆU_CHỨNG", candidates=["R51"], confidence=0.4)
    second = FinalEntity(text=raw_text, start=0, end=len(raw_text), type="TRIỆU_CHỨNG", assertions=["isHistorical"], confidence=0.9)

    result = Postprocessor({}).process([first, second], raw_text)

    assert len(result.entities) == 1
    assert result.entities[0].assertions == ["isHistorical"]
    assert result.entities[0].candidates == []
    assert result.report.exact_duplicates_removed == 1
    assert result.report.candidate_cleanups == 1