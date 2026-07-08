"""Apply ICD/RxNorm linkers to span candidates."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable, List, Tuple

from src.linking.icd10_linker import ICD10Linker
from src.linking.rxnorm_linker import RxNormLinker
from src.models import SpanCandidate
from src.rule_extractors import ENTITY_DIAGNOSIS, ENTITY_DRUG


def _append_source(source: List[str], marker: str) -> List[str]:
    """Append source marker once."""
    output = list(source)
    if marker not in output:
        output.append(marker)
    return output


def load_default_linkers(resource_dir: str | Path) -> Tuple[ICD10Linker, RxNormLinker]:
    """Load V0 ICD/RxNorm linkers from data_resources."""
    return ICD10Linker.from_resources(resource_dir), RxNormLinker.from_resources(resource_dir)


def link_mapping_candidates(
    candidates: Iterable[SpanCandidate],
    icd_linker: ICD10Linker,
    rxnorm_linker: RxNormLinker,
) -> Tuple[List[SpanCandidate], List[dict]]:
    """Populate mapping_candidates and return debug rows."""
    linked: List[SpanCandidate] = []
    debug_rows: List[dict] = []

    for candidate in candidates:
        if candidate.type_candidate == ENTITY_DIAGNOSIS:
            result = icd_linker.link(candidate.text)
        elif candidate.type_candidate == ENTITY_DRUG:
            result = rxnorm_linker.link(candidate.text)
        else:
            linked.append(candidate)
            continue

        source = _append_source(list(candidate.source), result.source)
        notes = candidate.notes
        if result.reason:
            notes = f"{notes}; {result.reason}".strip("; ")

        updated = replace(
            candidate,
            mapping_candidates=result.codes,
            source=source,
            notes=notes,
        )
        linked.append(updated)
        debug_rows.append(
            {
                "file_id": candidate.file_id,
                "text": candidate.text,
                "type": candidate.type_candidate,
                "start": candidate.start,
                "end": candidate.end,
                "codes": "|".join(result.codes),
                "source": result.source,
                "confidence": result.confidence,
                "matched_term": result.matched_term or "",
                "reason": result.reason or "",
            }
        )

    return linked, debug_rows
