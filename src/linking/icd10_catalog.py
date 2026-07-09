"""Full-catalog ICD-10 retriever over the BYT source table.

Loads `data_resources/icd10_byt_source.csv` (semicolon-delimited, BOM,
quoted multi-line cells) and builds an in-memory lexical index that maps a
free-text Vietnamese/English diagnosis query to a ranked shortlist of *real*
ICD-10 codes. It is deliberately stdlib-only and retrieval-oriented: it is not
meant to pick the single right code, only to surface a high-recall shortlist
that an LLM reranker then chooses from.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.linking.common import normalize_ascii_key, score_similarity

# `A00`, `A00.0`, `A00.11` etc. Rejects the numeric column-index row (`1;2;3...`)
# and block/range rows such as `A00-A09`.
ICD_CODE_RE = re.compile(r"^[A-Z]\d{2}(?:\.\d+)?$")

# CSV header names we care about (see file header row 1).
COL_CODE = "MÃ BỆNH"
COL_VI = "TÊN BỆNH"
COL_EN = "DISEASE NAME WHO 2019 (ENGLISH)"


@dataclass(frozen=True)
class IcdEntry:
    """One indexed ICD-10 catalog row."""

    code: str
    vi_name: str
    en_name: str
    tokens: Tuple[str, ...]

    @property
    def is_specific(self) -> bool:
        """True for 4+ character (sub-)codes, False for 3-char category headers."""
        return "." in self.code

    @property
    def label(self) -> str:
        """Readable label: Vietnamese name, with English appended when it adds info."""
        vi = self.vi_name.strip()
        en = self.en_name.strip()
        if vi and en and en.casefold() != vi.casefold():
            return f"{vi} ({en})"
        return vi or en


def _tokenize(text: str) -> Tuple[str, ...]:
    """Unaccented, casefolded, whitespace-collapsed tokens (len >= 2, dedup-safe)."""
    norm = normalize_ascii_key(text)
    return tuple(tok for tok in norm.split() if len(tok) >= 2)


class Icd10Catalog:
    """In-memory lexical retriever over the full BYT ICD-10 table."""

    def __init__(self, entries: List[IcdEntry]):
        self.entries: List[IcdEntry] = entries
        # Inverted index token -> entry indices, used as a cheap prefilter so we
        # only run the expensive similarity on entries that share a token.
        self._postings: Dict[str, List[int]] = defaultdict(list)
        for idx, entry in enumerate(entries):
            for tok in set(entry.tokens):
                self._postings[tok].append(idx)

    @classmethod
    def from_csv(cls, path: str | Path) -> "Icd10Catalog":
        """Load and index the ICD-10 catalog CSV."""
        csv_path = Path(path)
        entries: List[IcdEntry] = []
        seen_codes: set[str] = set()
        # Some cells contain very long quoted multi-line text; raise the field limit.
        csv.field_size_limit(10_000_000)
        with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for row in reader:
                code = (row.get(COL_CODE) or "").strip()
                if not ICD_CODE_RE.match(code):
                    continue
                vi_name = (row.get(COL_VI) or "").strip()
                en_name = (row.get(COL_EN) or "").strip()
                if not vi_name and not en_name:
                    continue
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                tokens = _tokenize(f"{vi_name} {en_name}")
                entries.append(
                    IcdEntry(code=code, vi_name=vi_name, en_name=en_name, tokens=tokens)
                )
        return cls(entries)

    def _score(self, query_tokens: set[str], query_norm: str, entry: IcdEntry) -> float:
        """Blend token-set overlap with fuzzy character similarity."""
        entry_tokens = set(entry.tokens)
        if not entry_tokens or not query_tokens:
            token_score = 0.0
        else:
            overlap = query_tokens & entry_tokens
            # Recall-friendly: reward covering the query terms rather than
            # penalising long catalog labels with many extra tokens.
            token_score = len(overlap) / len(query_tokens)
        vi_sim = score_similarity(query_norm, entry.vi_name)
        en_sim = score_similarity(query_norm, entry.en_name)
        return max(token_score, vi_sim, en_sim)

    def top_n(self, query: str, n: int = 10) -> List[Tuple[str, str]]:
        """Return up to `n` ranked `(code, label)` pairs for a diagnosis query."""
        query_norm = normalize_ascii_key(query)
        query_tokens = {tok for tok in query_norm.split() if len(tok) >= 2}
        if not query_tokens:
            return []

        # Prefilter: only entries sharing at least one query token.
        candidate_idx: set[int] = set()
        for tok in query_tokens:
            candidate_idx.update(self._postings.get(tok, ()))
        if not candidate_idx:
            return []

        scored: List[Tuple[float, int, str, IcdEntry]] = []
        for idx in candidate_idx:
            entry = self.entries[idx]
            score = self._score(query_tokens, query_norm, entry)
            if score <= 0.0:
                continue
            # Tie-break: prefer specific 4+ char codes over 3-char category headers,
            # then shorter/lexicographically-smaller codes for stability.
            specificity_rank = 0 if entry.is_specific else 1
            scored.append((-round(score, 6), specificity_rank, entry.code, entry))

        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        results: List[Tuple[str, str]] = []
        seen: set[str] = set()
        for _, _, code, entry in scored:
            if code in seen:
                continue
            seen.add(code)
            results.append((code, entry.label))
            if len(results) >= n:
                break
        return results


_DEFAULT_CATALOG: Optional[Icd10Catalog] = None


def get_default_catalog(resource_dir: str | Path) -> Icd10Catalog:
    """Load (and cache) the catalog from the standard resource directory."""
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = Icd10Catalog.from_csv(Path(resource_dir) / "icd10_byt_source.csv")
    return _DEFAULT_CATALOG
