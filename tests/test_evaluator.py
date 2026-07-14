from __future__ import annotations

from src.config import load_config
from src.evaluation import GoldenEvaluator, write_evaluation_report
from src.evaluation.evaluator import records_to_eval_entities
from src.evaluation.metrics import compute_assertion_metrics, compute_candidate_metrics, counts_by_type
from src.evaluation.models import EvaluationReport
from src.io_utils import read_json


def test_evaluator_end_to_end_mini_case(tmp_path) -> None:
    raw_text = "No fever. Pneumonia. Aspirin."
    gold = [
        {"text": "fever", "position": [3, 8], "type": "TRIỆU_CHỨNG", "assertions": ["isNegated"]},
        {"text": "Pneumonia", "position": [10, 19], "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["J18.9"]},
        {"text": "Aspirin", "position": [21, 28], "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
    ]
    pred = [
        {"text": "fever", "position": [3, 8], "type": "TRIỆU_CHỨNG", "assertions": []},
        {"text": "Pneumonia", "position": [10, 19], "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["J18.9", "J18"]},
        {"text": "No", "position": [0, 2], "type": "TRIỆU_CHỨNG", "assertions": []},
    ]
    evaluator = GoldenEvaluator()

    result = evaluator.evaluate_records(file_id="mini", raw_text=raw_text, gold_records=gold, pred_records=pred)

    assert result.exact_counts.tp == 2
    assert result.exact_counts.fp == 1
    assert result.exact_counts.fn == 1
    assert len(result.assertion_mismatches) == 1
    assert len(result.candidate_mismatches) == 1


def test_write_evaluation_report(tmp_path) -> None:
    raw_text = "fever"
    record = {"text": "fever", "position": [0, 5], "type": "TRIỆU_CHỨNG", "assertions": []}
    evaluator = GoldenEvaluator()
    result = evaluator.evaluate_records(file_id="1", raw_text=raw_text, gold_records=[record], pred_records=[record])
    entities = records_to_eval_entities("1", [record])
    evaluation_report = EvaluationReport(
        files=[result],
        overall_exact=result.exact_counts,
        overall_relaxed=result.relaxed_counts,
        by_type_exact=counts_by_type(entities, entities, result.exact_pairs),
        by_type_relaxed=counts_by_type(entities, entities, result.relaxed_pairs),
        assertion_metrics=compute_assertion_metrics(result.exact_pairs),
        candidate_metrics=compute_candidate_metrics(result.exact_pairs),
        error_category_counts={},
    )

    write_evaluation_report(evaluation_report, tmp_path)

    assert read_json(tmp_path / "evaluation_summary.json")["exact"]["f1"] == 1.0
    assert (tmp_path / "per_file_metrics.csv").is_file()
    assert (tmp_path / "error_cases.jsonl").is_file()
    assert (tmp_path / "samples.md").is_file()


def test_evaluator_on_golden_self_match_has_perfect_exact_metrics() -> None:
    config = load_config("configs/default.yaml")
    evaluator = GoldenEvaluator(config.raw.get("evaluation", {}), validation_config=config.raw.get("prediction_validation", {}))

    report = evaluator.evaluate_directories(
        input_dir=config.path("golden_input_dir"),
        gold_dir=config.path("golden_gold_dir"),
        pred_dir=config.path("golden_gold_dir"),
        expected_count=20,
    )

    assert report.gold_entities == 370
    assert report.pred_entities == 370
    assert report.overall_exact.tp == 370
    assert report.overall_exact.fp == 0
    assert report.overall_exact.fn == 0
    assert report.overall_exact.f1 == 1.0
    assert report.overall_relaxed.f1 == 1.0