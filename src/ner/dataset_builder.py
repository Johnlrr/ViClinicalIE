from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.io_utils import read_json, read_text, write_json, write_text
from src.ner.bio import EntityAnnotation, NerExample, records_to_entities, validate_example_offsets


@dataclass(slots=True)
class NerDatasetSummary:
    source_name: str
    input_dir: str
    annotation_dir: str
    output_path: str
    file_count: int = 0
    entity_count: int = 0
    offset_error_count: int = 0
    overlap_conflict_count: int = 0
    label_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "input_dir": self.input_dir,
            "annotation_dir": self.annotation_dir,
            "output_path": self.output_path,
            "file_count": self.file_count,
            "entity_count": self.entity_count,
            "offset_error_count": self.offset_error_count,
            "overlap_conflict_count": self.overlap_conflict_count,
            "label_counts": dict(sorted(self.label_counts.items())),
            "errors": self.errors,
        }


def build_ner_dataset(
    *,
    input_dir: str | Path,
    annotation_dir: str | Path,
    source_name: str,
    output_path: str | Path,
    label_types: set[str] | None = None,
) -> tuple[list[NerExample], NerDatasetSummary]:
    input_path = Path(input_dir)
    annotation_path = Path(annotation_dir)
    output = Path(output_path)
    examples: list[NerExample] = []
    label_counter: Counter[str] = Counter()
    summary = NerDatasetSummary(
        source_name=source_name,
        input_dir=str(input_path),
        annotation_dir=str(annotation_path),
        output_path=str(output),
    )

    for text_file in sorted(input_path.glob("*.txt"), key=lambda item: _natural_key(item.stem)):
        annotation_file = annotation_path / f"{text_file.stem}.json"
        if not annotation_file.exists():
            summary.errors.append(f"{text_file.stem}: missing annotation file {annotation_file}")
            continue
        raw_text = read_text(text_file)
        records = read_json(annotation_file)
        if not isinstance(records, list):
            summary.errors.append(f"{text_file.stem}: annotation JSON is not a list")
            continue
        before_count = _count_candidate_records(records, label_types)
        entities, errors = records_to_entities(records, raw_text, source=source_name, label_types=label_types)
        summary.errors.extend(f"{text_file.stem}: {error}" for error in errors)
        summary.offset_error_count += len(errors)
        summary.overlap_conflict_count += max(0, before_count - len(entities) - len(errors))
        example = NerExample(file_id=text_file.stem, text=raw_text, entities=entities, source=source_name)
        example_errors = validate_example_offsets(example)
        summary.errors.extend(example_errors)
        summary.offset_error_count += len(example_errors)
        examples.append(example)
        label_counter.update(entity.type for entity in entities)

    summary.file_count = len(examples)
    summary.entity_count = sum(len(example.entities) for example in examples)
    summary.label_counts = dict(label_counter)
    return examples, summary


def write_ner_dataset(examples: list[NerExample], output_path: str | Path) -> None:
    lines = [json.dumps(example.to_dict(), ensure_ascii=False) for example in examples]
    write_text(output_path, "\n".join(lines) + ("\n" if lines else ""))


def write_ner_dataset_report(summary: NerDatasetSummary, report_dir: str | Path) -> None:
    target = Path(report_dir)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / f"{summary.source_name}_summary.json", summary.to_dict())
    rows = ["type,count"]
    for entity_type, count in sorted(summary.label_counts.items()):
        rows.append(f"{entity_type},{count}")
    write_text(target / f"{summary.source_name}_label_distribution.csv", "\n".join(rows) + "\n")


def examples_from_jsonl(path: str | Path) -> list[NerExample]:
    examples: list[NerExample] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        entities = [
            EntityAnnotation(
                text=str(item["text"]),
                start=int(item["start"]),
                end=int(item["end"]),
                type=str(item["type"]),
                source=str(item.get("source", data.get("source", ""))),
                score=float(item["score"]) if item.get("score") is not None else None,
                metadata=dict(item.get("metadata", {})),
            )
            for item in data.get("entities", [])
        ]
        examples.append(NerExample(file_id=str(data.get("file_id", "")), text=str(data.get("text", "")), entities=entities, source=str(data.get("source", ""))))
    return examples


def _count_candidate_records(records: list[dict[str, Any]], label_types: set[str] | None) -> int:
    if label_types is None:
        return len(records)
    return sum(1 for record in records if str(record.get("type", "")) in label_types)


def _natural_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
