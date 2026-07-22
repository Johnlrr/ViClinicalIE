from __future__ import annotations

from src.data_types import SpanCandidate
from src.pipeline import ClinicalIEPipeline


def test_pipeline_can_replay_candidates_without_extractors_or_model() -> None:
    raw = "sốt"
    pipeline = object.__new__(ClinicalIEPipeline)
    pipeline.raw_config = {"type_resolution": {}}
    entities = pipeline.resolve_candidates(raw, [SpanCandidate(raw, 0, 3, "TRIỆU_CHỨNG", "gliner", .8)])
    assert [(entity.text, entity.type) for entity in entities] == [("sốt", "TRIỆU_CHỨNG")]


def test_submission_formatter_does_not_expose_internal_trace() -> None:
    raw = "sốt"
    pipeline = object.__new__(ClinicalIEPipeline)
    pipeline.raw_config = {"type_resolution": {}}
    from src.formatting import PredictionFormatter
    pipeline.formatter = PredictionFormatter()
    entities = pipeline.resolve_candidates(raw, [SpanCandidate(raw, 0, 3, "TRIỆU_CHỨNG", "gliner", .8)])
    result = pipeline.process_resolved_ner(raw, entities, file_id="1")
    assert result.records == [{"text": "sốt", "position": [0, 3], "type": "TRIỆU_CHỨNG", "assertions": []}]
    assert "provenance" not in result.records[0]