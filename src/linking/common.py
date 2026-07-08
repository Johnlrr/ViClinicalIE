"""Shared helpers for local candidate mapping."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from src.normalization import normalize_for_matching, normalize_vietnamese_diacritics


@dataclass(frozen=True)
class MappingEntry:
    """One local ICD/RxNorm mapping row."""

    term: str
    code: str
    label: str
    alias_group: str
    priority: int
    notes: str = ""

    @property
    def normalized_term(self) -> str:
        """Normalized term for matching."""
        return normalize_mapping_text(self.term)


@dataclass(frozen=True)
class MappingResult:
    """Candidate mapping result with debug metadata."""

    codes: List[str]
    source: str
    confidence: float
    matched_term: Optional[str] = None
    reason: Optional[str] = None


def normalize_mapping_text(text: str) -> str:
    """Normalize text for mapping lookup."""
    normalized = normalize_for_matching(text)
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[()\\[\\]{},;:/]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def normalize_ascii_key(text: str) -> str:
    """Return a no-diacritic normalized key for fallback matching."""
    return normalize_mapping_text(normalize_vietnamese_diacritics(text))


def read_mapping_entries(path: str | Path) -> List[MappingEntry]:
    """Read curated mapping CSV resources."""
    resource_path = Path(path)
    if not resource_path.exists():
        return []

    entries: List[MappingEntry] = []
    with resource_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = (row.get("term") or "").strip()
            code = (row.get("code") or "").strip()
            if not term or not code:
                continue
            try:
                priority = int((row.get("priority") or "1").strip())
            except ValueError:
                priority = 1
            entries.append(
                MappingEntry(
                    term=term,
                    code=code,
                    label=(row.get("label") or "").strip(),
                    alias_group=(row.get("alias_group") or term).strip(),
                    priority=priority,
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return entries


def read_aliases(path: str | Path, alias_type: str) -> Dict[str, str]:
    """Read term->canonical aliases for one mapping type."""
    resource_path = Path(path)
    if not resource_path.exists():
        return {}

    aliases: Dict[str, str] = {}
    with resource_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("type") or "").strip().lower() != alias_type.lower():
                continue
            term = normalize_mapping_text(row.get("term") or "")
            canonical = normalize_mapping_text(row.get("canonical") or "")
            if term and canonical:
                aliases[term] = canonical
    return aliases


def unique_codes(entries: Iterable[MappingEntry], limit: int = 1) -> List[str]:
    """Return stable unique codes sorted by priority."""
    codes: List[str] = []
    for entry in sorted(entries, key=lambda item: (item.priority, len(item.term))):
        if entry.code not in codes:
            codes.append(entry.code)
        if len(codes) >= limit:
            break
    return codes


def score_similarity(left: str, right: str) -> float:
    """Conservative fuzzy score combining char ratio and token Jaccard."""
    left_norm = normalize_mapping_text(left)
    right_norm = normalize_mapping_text(right)
    if not left_norm or not right_norm:
        return 0.0

    char_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens | right_tokens else 0.0
    ascii_score = SequenceMatcher(None, normalize_ascii_key(left_norm), normalize_ascii_key(right_norm)).ratio()
    return max(char_score, ascii_score, token_score)
