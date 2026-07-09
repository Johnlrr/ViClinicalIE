"""Full-catalog RxNorm retriever over RXNCONSO.RRF.

Loads `data_resources/RXNCONSO.RRF` (pipe-delimited, no header), keeps only
non-suppressed rows, prefers `SAB=RXNORM`, and indexes every atom string
(`STR`) back to its `RXCUI`. `top_n(query)` strips dose/route/frequency noise
from a drug span, normalizes it, and returns a ranked shortlist of real RXCUIs
for an LLM reranker to choose from. Stdlib-only.

RRF field indices used: 0=RXCUI, 11=SAB, 12=TTY, 14=STR, 16=SUPPRESS.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.linking.common import normalize_ascii_key, score_similarity
from src.linking.rxnorm_linker import DOSE_AND_SIG_PATTERN

# TTY values that denote clinically useful concepts; we keep everything but use
# this to nudge ingredient/brand/clinical-drug atoms ahead on score ties.
_PREFERRED_TTY = {"IN", "PIN", "MIN", "BN", "SCD", "SBD", "SCDC", "SBDC", "PSN", "SY"}


def _tokenize(text: str) -> Tuple[str, ...]:
    """Unaccented, casefolded tokens (len >= 2)."""
    norm = normalize_ascii_key(text)
    return tuple(tok for tok in norm.split() if len(tok) >= 2)


def _strip_sig(text: str) -> str:
    """Remove dose/route/frequency tokens before matching a drug string."""
    stripped = DOSE_AND_SIG_PATTERN.sub(" ", text)
    stripped = re.sub(r"\b(?:succinate|xl|xr|sr|dr|ec)\b", " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped or text


@dataclass(frozen=True)
class RxEntry:
    """One indexed RxNorm atom string."""

    rxcui: str
    string: str
    tokens: Tuple[str, ...]
    is_rxnorm: bool
    tty: str

    @property
    def preference_rank(self) -> int:
        """Lower is better: RXNORM+preferred-TTY first, other-SAB atoms last."""
        rank = 0 if self.is_rxnorm else 2
        if self.tty not in _PREFERRED_TTY:
            rank += 1
        return rank


class RxNormCatalog:
    """In-memory lexical retriever over the full RXNCONSO atom table."""

    def __init__(self, entries: List[RxEntry]):
        self.entries: List[RxEntry] = entries
        self._postings: Dict[str, List[int]] = defaultdict(list)
        # Preferred readable label per rxcui for shortlist display.
        self._label_by_cui: Dict[str, str] = {}
        for idx, entry in enumerate(entries):
            for tok in set(entry.tokens):
                self._postings[tok].append(idx)
            prev = self._label_by_cui.get(entry.rxcui)
            if prev is None or entry.preference_rank < 0:
                self._label_by_cui.setdefault(entry.rxcui, entry.string)

    @classmethod
    def from_rrf(cls, path: str | Path) -> "RxNormCatalog":
        """Load and index RXNCONSO.RRF, keeping SUPPRESS=N atoms."""
        rrf_path = Path(path)
        entries: List[RxEntry] = []
        # Dedupe identical (rxcui, normalized-string) pairs to keep the index tight.
        seen: set[Tuple[str, str]] = set()
        label_by_cui: Dict[str, str] = {}
        with rrf_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for line in fh:
                if not line:
                    continue
                # Trailing '|' yields an empty final field; split keeps all fields.
                fields = line.rstrip("\n").rstrip("\r").split("|")
                if len(fields) < 17:
                    continue
                if fields[16] != "N":  # SUPPRESS
                    continue
                rxcui = fields[0].strip()
                string = fields[14].strip()
                if not rxcui or not string:
                    continue
                sab = fields[11].strip()
                tty = fields[12].strip()
                is_rxnorm = sab == "RXNORM"
                norm = normalize_ascii_key(string)
                if not norm:
                    continue
                key = (rxcui, norm)
                if key in seen:
                    continue
                seen.add(key)
                tokens = tuple(tok for tok in norm.split() if len(tok) >= 2)
                if not tokens:
                    continue
                entries.append(
                    RxEntry(
                        rxcui=rxcui,
                        string=string,
                        tokens=tokens,
                        is_rxnorm=is_rxnorm,
                        tty=tty,
                    )
                )
                # Prefer an RXNORM ingredient/name atom as the display label.
                if rxcui not in label_by_cui or (is_rxnorm and tty in _PREFERRED_TTY):
                    label_by_cui[rxcui] = string
        catalog = cls(entries)
        catalog._label_by_cui = label_by_cui
        return catalog

    def _score(self, query_tokens: set[str], query_norm: str, entry: RxEntry) -> float:
        """Blend token-set overlap with fuzzy character similarity."""
        entry_tokens = set(entry.tokens)
        if not entry_tokens or not query_tokens:
            token_score = 0.0
        else:
            overlap = query_tokens & entry_tokens
            token_score = len(overlap) / len(query_tokens)
        char_sim = score_similarity(query_norm, entry.string)
        return max(token_score, char_sim)

    def top_n(self, query: str, n: int = 10) -> List[Tuple[str, str]]:
        """Return up to `n` ranked `(rxcui, label)` pairs for a drug query."""
        stripped = _strip_sig(query)
        query_norm = normalize_ascii_key(stripped)
        query_tokens = {tok for tok in query_norm.split() if len(tok) >= 2}
        if not query_tokens:
            return []

        candidate_idx: set[int] = set()
        for tok in query_tokens:
            candidate_idx.update(self._postings.get(tok, ()))
        if not candidate_idx:
            return []

        # Keep the best (score, preference) per rxcui.
        best: Dict[str, Tuple[float, int]] = {}
        for idx in candidate_idx:
            entry = self.entries[idx]
            score = self._score(query_tokens, query_norm, entry)
            if score <= 0.0:
                continue
            prev = best.get(entry.rxcui)
            candidate = (round(score, 6), entry.preference_rank)
            if prev is None or (candidate[0], -candidate[1]) > (prev[0], -prev[1]):
                best[entry.rxcui] = candidate

        ranked = sorted(
            best.items(),
            key=lambda kv: (-kv[1][0], kv[1][1], len(kv[0]), kv[0]),
        )
        results: List[Tuple[str, str]] = []
        for rxcui, _ in ranked[:n]:
            label = self._label_by_cui.get(rxcui, rxcui)
            results.append((rxcui, label))
        return results


_DEFAULT_CATALOG: Optional[RxNormCatalog] = None


def get_default_catalog(resource_dir: str | Path) -> RxNormCatalog:
    """Load (and cache) the catalog from the standard resource directory."""
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = RxNormCatalog.from_rrf(Path(resource_dir) / "RXNCONSO.RRF")
    return _DEFAULT_CATALOG
