from __future__ import annotations

from src.ner.data_validator import validate_ner_jsonl


def test_shared_example_dataset_is_valid() -> None:
    report = validate_ner_jsonl("data/golden/ner_data_example.jsonl")
    assert report.ok, report.errors


def test_validator_detects_offset_mismatch(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"file_id":"x","text":"sốt","source":"x","generator_version":"1","seed":1,"entities":[{"text":"ho","start":0,"end":2,"type":"TRIỆU_CHỨNG","source":"x","metadata":{"template_family":"t","concept_family":"c","noise_profile":"clean"}}]}\n', encoding="utf-8")
    report = validate_ner_jsonl(path)
    assert not report.ok
    assert {error["code"] for error in report.errors} == {"offset_mismatch"}