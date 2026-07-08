"""Curated ICD-10 linker for diagnosis candidates."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from src.linking.common import (
    MappingEntry,
    MappingResult,
    normalize_mapping_text,
    read_aliases,
    read_mapping_entries,
    score_similarity,
    unique_codes,
)


ICD_DROP_PHRASES = [
    "không xác định",
    "không đặc hiệu",
    "không biệt định",
    "chưa có biến chứng",
]


class ICD10Linker:
    """Local deterministic ICD-10 linker."""

    def __init__(self, entries: List[MappingEntry], aliases: Dict[str, str] | None = None):
        self.entries = entries
        self.aliases = aliases or {}
        self.by_norm: Dict[str, List[MappingEntry]] = defaultdict(list)
        for entry in entries:
            self.by_norm[entry.normalized_term].append(entry)

    @classmethod
    def from_resources(cls, resource_dir: str | Path) -> "ICD10Linker":
        """Load ICD resources from data_resources."""
        resource_path = Path(resource_dir)
        entries = read_mapping_entries(resource_path / "icd10_curated_map.csv")
        aliases = read_aliases(resource_path / "mapping_aliases.csv", "icd")
        return cls(entries, aliases)

    def _variants(self, text: str) -> List[str]:
        """Generate normalized diagnosis lookup variants."""
        base = normalize_mapping_text(text)
        variants = [base]

        cleaned = base
        for phrase in ICD_DROP_PHRASES:
            cleaned = cleaned.replace(normalize_mapping_text(phrase), " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and cleaned not in variants:
            variants.append(cleaned)

        for alias, canonical in self.aliases.items():
            if alias == base or alias in base:
                replaced = base.replace(alias, canonical).strip()
                if replaced and replaced not in variants:
                    variants.append(replaced)
                if canonical not in variants:
                    variants.append(canonical)

        return variants

    def link(self, text: str, top_k: int = 1) -> MappingResult:
        """Link a diagnosis mention to ICD-10 candidates."""
        variants = self._variants(text)

        for variant in variants:
            if variant in self.by_norm:
                return MappingResult(
                    codes=unique_codes(self.by_norm[variant], limit=top_k),
                    source="icd_exact",
                    confidence=1.0,
                    matched_term=variant,
                )

        for variant in variants:
            canonical = self.aliases.get(variant)
            if canonical and canonical in self.by_norm:
                return MappingResult(
                    codes=unique_codes(self.by_norm[canonical], limit=top_k),
                    source="icd_alias",
                    confidence=0.96,
                    matched_term=canonical,
                )

        best_entry = None
        best_score = 0.0
        for variant in variants:
            for entry in self.entries:
                score = score_similarity(variant, entry.normalized_term)
                if score > best_score:
                    best_entry = entry
                    best_score = score

        if best_entry is not None and best_score >= 0.88:
            return MappingResult(
                codes=[best_entry.code],
                source="icd_fuzzy",
                confidence=round(best_score, 4),
                matched_term=best_entry.term,
            )

        return MappingResult(
            codes=[],
            source="icd_unmapped",
            confidence=0.0,
            reason="no_icd_candidate_above_threshold",
        )
