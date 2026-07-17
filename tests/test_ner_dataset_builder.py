from __future__ import annotations

import json
from pathlib import Path

from src.ner.dataset_builder import build_ner_dataset, write_ner_dataset


def test_build_ner_dataset_from_fake_gold(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    gold_dir = tmp_path / "gold"
    input_dir.mkdir()
    gold_dir.mkdir()
    raw = "Không sốt. Có đau ngực."
    (input_dir / "1.txt").write_text(raw, encoding="utf-8")
    (gold_dir / "1.json").write_text(
        json.dumps(
            [
                {"text": "sốt", "position": [6, 9], "type": "TRIỆU_CHỨNG"},
                {"text": "đau ngực", "position": [14, 22], "type": "TRIỆU_CHỨNG"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "dev_gold.jsonl"
    examples, summary = build_ner_dataset(input_dir=input_dir, annotation_dir=gold_dir, source_name="gold", output_path=output_path)
    write_ner_dataset(examples, output_path)

    assert summary.file_count == 1
    assert summary.entity_count == 2
    assert summary.offset_error_count == 0
    assert output_path.read_text(encoding="utf-8").count("\n") == 1


def test_build_ner_dataset_filters_weak_types(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    pred_dir = tmp_path / "pred"
    input_dir.mkdir()
    pred_dir.mkdir()
    raw = "metoprolol và đau ngực"
    (input_dir / "1.txt").write_text(raw, encoding="utf-8")
    (pred_dir / "1.json").write_text(
        json.dumps(
            [
                {"text": "metoprolol", "position": [0, 10], "type": "THUỐC"},
                {"text": "đau ngực", "position": [14, 22], "type": "TRIỆU_CHỨNG"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    examples, summary = build_ner_dataset(
        input_dir=input_dir,
        annotation_dir=pred_dir,
        source_name="phase9_weak",
        output_path=tmp_path / "weak.jsonl",
        label_types={"TRIỆU_CHỨNG"},
    )

    assert summary.entity_count == 1
    assert examples[0].entities[0].text == "đau ngực"
