from __future__ import annotations

from src.data_types import FinalEntity
from src.formatting import PredictionFormatter, format_entity, format_entities, write_prediction_json
from src.io_utils import read_json


def test_format_symptom_includes_assertions_no_candidates() -> None:
    entity = FinalEntity(text="sốt", start=6, end=9, type="TRIỆU_CHỨNG", assertions=["isNegated"])

    record = format_entity(entity)

    assert record == {"text": "sốt", "position": [6, 9], "type": "TRIỆU_CHỨNG", "assertions": ["isNegated"]}
    assert "candidates" not in record


def test_format_lab_includes_empty_assertions_no_candidates() -> None:
    entity = FinalEntity(text="Na", start=0, end=2, type="TÊN_XÉT_NGHIỆM")

    record = format_entity(entity)

    assert record == {"text": "Na", "position": [0, 2], "type": "TÊN_XÉT_NGHIỆM", "assertions": []}


def test_format_drug_includes_candidates() -> None:
    entity = FinalEntity(text="aspirin", start=0, end=7, type="THUỐC", candidates=["1191", "1191"])

    record = format_entity(entity)

    assert record["candidates"] == ["1191"]


def test_format_diagnosis_includes_empty_candidates() -> None:
    entity = FinalEntity(text="viêm phổi", start=0, end=9, type="CHẨN_ĐOÁN")

    record = format_entity(entity)

    assert record["candidates"] == []


def test_formatter_does_not_emit_confidence_or_provenance() -> None:
    entity = FinalEntity(text="sốt", start=0, end=3, type="TRIỆU_CHỨNG", confidence=0.9, provenance={"debug": True})

    record = format_entity(entity)

    assert "confidence" not in record
    assert "provenance" not in record


def test_write_prediction_json_utf8(tmp_path) -> None:
    records = format_entities([FinalEntity(text="tăng huyết áp", start=0, end=13, type="CHẨN_ĐOÁN", candidates=["I10"])])
    output_path = tmp_path / "1.json"

    write_prediction_json(records, output_path)

    assert read_json(output_path)[0]["text"] == "tăng huyết áp"


def test_prediction_formatter_write_returns_records(tmp_path) -> None:
    formatter = PredictionFormatter({})
    entity = FinalEntity(text="sốt", start=0, end=3, type="TRIỆU_CHỨNG")

    records = formatter.write([entity], tmp_path / "pred.json")

    assert records == [{"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []}]