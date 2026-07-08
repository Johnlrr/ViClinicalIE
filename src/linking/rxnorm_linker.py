"""Curated RxNorm linker for drug candidates."""

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


DOSE_AND_SIG_PATTERN = re.compile(
    r"\b(?:\d+(?:[,.]\d+)?(?:-\d+(?:[,.]\d+)?)?\s*(?:mg|mcg|g|gram|ml|mg/ml|iu|unit|units?)"
    r"|po|iv|im|sc|bid|tid|qid|daily|q\d+h|qam|qhs|prn|x\s*\d+|oral|tablet|capsule|suspension)\b",
    re.IGNORECASE,
)


class RxNormLinker:
    """Local deterministic RxNorm linker."""

    def __init__(self, entries: List[MappingEntry], aliases: Dict[str, str] | None = None):
        self.entries = entries
        self.aliases = aliases or {}
        self.by_norm: Dict[str, List[MappingEntry]] = defaultdict(list)
        for entry in entries:
            self.by_norm[entry.normalized_term].append(entry)

    @classmethod
    def from_resources(cls, resource_dir: str | Path) -> "RxNormLinker":
        """Load RxNorm resources from data_resources."""
        resource_path = Path(resource_dir)
        entries = read_mapping_entries(resource_path / "rxnorm_curated_map.csv")
        aliases = read_aliases(resource_path / "mapping_aliases.csv", "rxnorm")
        return cls(entries, aliases)

    def _strip_sig(self, text: str) -> str:
        """Remove dose/route/frequency tokens for ingredient fallback."""
        stripped = DOSE_AND_SIG_PATTERN.sub(" ", text)
        stripped = re.sub(r"\b(?:succinate|xl|xr|sr|dr|ec)\b", " ", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return stripped

    def _variants(self, text: str) -> List[str]:
        """Generate normalized drug lookup variants."""
        base = normalize_mapping_text(text)
        variants = [base]

        stripped = normalize_mapping_text(self._strip_sig(base))
        if stripped and stripped not in variants:
            variants.append(stripped)

        for alias, canonical in self.aliases.items():
            if alias == base or alias in base or alias == stripped or alias in stripped:
                for source in (base, stripped):
                    replaced = source.replace(alias, canonical).strip()
                    if replaced and replaced not in variants:
                        variants.append(replaced)
                if canonical not in variants:
                    variants.append(canonical)

        # Ingredient fallback: if a known short term occurs in the drug phrase,
        # test it directly after full phrase and stripped phrase exact attempts.
        for entry in sorted(self.entries, key=lambda item: len(item.normalized_term), reverse=True):
            term = entry.normalized_term
            if term and (base.startswith(term) or f" {term} " in f" {base} "):
                if term not in variants:
                    variants.append(term)
        return variants

    def link(self, text: str, top_k: int = 1) -> MappingResult:
        """Link a drug mention to RxNorm candidates."""
        variants = self._variants(text)

        for variant in variants:
            if variant in self.by_norm:
                return MappingResult(
                    codes=unique_codes(self.by_norm[variant], limit=top_k),
                    source="rxnorm_exact" if variant == variants[0] else "rxnorm_alias_or_ingredient",
                    confidence=1.0 if variant == variants[0] else 0.93,
                    matched_term=variant,
                )

        best_entry = None
        best_score = 0.0
        for variant in variants:
            for entry in self.entries:
                score = score_similarity(variant, entry.normalized_term)
                if score > best_score:
                    best_entry = entry
                    best_score = score

        if best_entry is not None and best_score >= 0.86:
            return MappingResult(
                codes=[best_entry.code],
                source="rxnorm_fuzzy",
                confidence=round(best_score, 4),
                matched_term=best_entry.term,
            )

        return MappingResult(
            codes=[],
            source="rxnorm_unmapped",
            confidence=0.0,
            reason="no_rxnorm_candidate_above_threshold",
        )
