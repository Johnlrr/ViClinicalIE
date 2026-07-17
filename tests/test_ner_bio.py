from __future__ import annotations

from src.ner.bio import EntityAnnotation, char_bio_to_entities, entities_to_char_bio, records_to_entities, validate_example_offsets, NerExample


def test_records_to_entities_keeps_valid_offsets() -> None:
    raw = "Không sốt. Có đau ngực."
    records = [{"text": "sốt", "position": [6, 9], "type": "TRIỆU_CHỨNG"}]

    entities, errors = records_to_entities(records, raw, source="gold")

    assert errors == []
    assert entities[0].text == "sốt"
    assert entities[0].start == 6


def test_records_to_entities_reports_invalid_offsets() -> None:
    raw = "Không sốt."
    records = [{"text": "ho", "position": [6, 9], "type": "TRIỆU_CHỨNG"}]

    entities, errors = records_to_entities(records, raw, source="gold")

    assert entities == []
    assert errors


def test_overlapping_records_prefers_longer_span() -> None:
    raw = "đau bụng vùng hạ sườn phải"
    records = [
        {"text": "đau bụng", "position": [0, 8], "type": "TRIỆU_CHỨNG"},
        {"text": "đau bụng vùng hạ sườn phải", "position": [0, len(raw)], "type": "TRIỆU_CHỨNG"},
    ]

    entities, errors = records_to_entities(records, raw, source="gold")

    assert errors == []
    assert len(entities) == 1
    assert entities[0].text == raw


def test_char_bio_roundtrip_simple_symptom() -> None:
    raw = "Không sốt."
    labels = entities_to_char_bio(raw, [EntityAnnotation("sốt", 6, 9, "TRIỆU_CHỨNG")])

    assert labels[6] == "B-TRIỆU_CHỨNG"
    assert labels[7] == "I-TRIỆU_CHỨNG"
    entities = char_bio_to_entities(raw, labels)
    assert [(entity.text, entity.start, entity.end, entity.type) for entity in entities] == [("sốt", 6, 9, "TRIỆU_CHỨNG")]


def test_validate_example_offsets_detects_mismatch() -> None:
    example = NerExample(file_id="x", text="Không sốt", entities=[EntityAnnotation("ho", 6, 9, "TRIỆU_CHỨNG")])

    assert validate_example_offsets(example)
