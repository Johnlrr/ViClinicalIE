"""Submission JSON and zip writer for V0 outputs."""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from src.assertion import ASSERTION_ORDER
from src.models import ClinicalDocument, SpanCandidate
from src.rule_extractors import ENTITY_DIAGNOSIS, ENTITY_DRUG, ENTITY_LAB_NAME, ENTITY_LAB_RESULT


MAPPING_TYPES = {ENTITY_DIAGNOSIS, ENTITY_DRUG}
LAB_TYPES = {ENTITY_LAB_NAME, ENTITY_LAB_RESULT}


def _ordered_assertions(candidate: SpanCandidate) -> List[str]:
    """Return stable, schema-valid assertion list for final output."""
    if candidate.type_candidate in LAB_TYPES:
        return []
    found = set(candidate.assertion_candidates)
    return [assertion for assertion in ASSERTION_ORDER if assertion in found]


def candidate_to_entity(candidate: SpanCandidate) -> Dict[str, object]:
    """Convert an accepted span candidate to submission entity format."""
    entity: Dict[str, object] = {
        "text": candidate.text,
        "position": [candidate.start, candidate.end],
        "type": candidate.type_candidate,
        "assertions": _ordered_assertions(candidate),
    }
    if candidate.type_candidate in MAPPING_TYPES:
        entity["candidates"] = list(candidate.mapping_candidates)
    return entity


def group_entities_by_file(candidates: Iterable[SpanCandidate]) -> Dict[str, List[Dict[str, object]]]:
    """Group accepted candidates into sorted entity dicts by file_id."""
    grouped: Dict[str, List[SpanCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.should_output and candidate.span_status == "accepted":
            grouped[candidate.file_id].append(candidate)

    return {
        file_id: [
            candidate_to_entity(candidate)
            for candidate in sorted(file_candidates, key=lambda item: (item.start, item.end, item.type_candidate))
        ]
        for file_id, file_candidates in grouped.items()
    }


def write_output_files(
    candidates: Iterable[SpanCandidate],
    documents: Sequence[ClinicalDocument],
    output_dir: str | Path,
) -> Dict[str, int]:
    """Write one JSON list per input file, including [] for empty files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    entities_by_file = group_entities_by_file(candidates)
    counts: Dict[str, int] = {}

    for doc in sorted(documents, key=lambda item: int(item.file_id)):
        entities = entities_by_file.get(doc.file_id, [])
        counts[doc.file_id] = len(entities)
        file_path = output_path / f"{doc.file_id}.json"
        file_path.write_text(
            json.dumps(entities, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )

    return counts


def create_output_zip(output_dir: str | Path, zip_path: str | Path) -> None:
    """Create output.zip with top-level output/ folder."""
    output_path = Path(output_dir)
    archive_path = Path(zip_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for json_file in sorted(output_path.glob("*.json"), key=lambda path: int(path.stem)):
            zipf.write(json_file, f"output/{json_file.name}")
