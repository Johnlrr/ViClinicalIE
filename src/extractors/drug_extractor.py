from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_types import Chunk, SpanCandidate
from src.extractors.base import BaseExtractor, ExtractionContext
from src.extractors.utils import dedupe_candidates, find_phrase_matches, make_span_candidate, trim_trailing_punctuation
from src.linking.terminology_normalizer import normalize_no_diacritics_for_lookup, tokenize_for_lookup


_TAIL_TOKEN_RE = re.compile(
    r"""
    (?:\s+
      (?:
        \d+(?:[\.,]\d+)?(?:\s*-\s*\d+(?:[\.,]\d+)?)?\s*(?:mg/ml|mg|mcg|g|gram|ml|units?|đơn\s*vị|%)
        |po|iv|im|sc|oral|uống|tiêm|truyền|nebs?|nebulizer
        |daily|bid|tid|qid|q\d+h|prn|qam|qhs|x\s*\d+|/ngày|lần/ngày|ngày
      )
    )+
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_STRENGTH_RE = re.compile(r"\d+(?:[\.,]\d+)?(?:\s*-\s*\d+(?:[\.,]\d+)?)?\s*(?:mg/ml|mg|mcg|g|gram|ml|units?|đơn\s*vị|%)", re.I)
_ROUTE_RE = re.compile(r"\b(?:po|iv|im|sc|oral|uống|tiêm|truyền|nebs?|nebulizer)\b", re.I)
_FREQ_RE = re.compile(r"\b(?:daily|bid|tid|qid|q\d+h|prn|qam|qhs|x\s*\d+|ngày|lần/ngày)\b|/ngày", re.I)
_STOP_FIRST_TOKENS = {"oral", "tablet", "capsule", "solution", "injectable", "mg", "ml", "and", "with"}


class DrugExtractor(BaseExtractor):
    name = "drug_rule"

    def __init__(
        self,
        *,
        rxnorm_alias_path: str | Path | None = None,
        manual_alias_path: str | Path | None = None,
        alias_rows: Sequence[Mapping[str, Any]] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.config = dict(config or {})
        self.min_alias_length = int(self.config.get("min_alias_length", 3))
        self.max_alias_length = int(self.config.get("max_alias_length", 80))
        self.max_aliases_per_first_token = int(self.config.get("max_aliases_per_first_token", 250))
        rows: list[dict[str, Any]] = []
        if rxnorm_alias_path and Path(rxnorm_alias_path).exists():
            frame = pd.read_parquet(rxnorm_alias_path)
            wanted_cols = [col for col in ["alias", "alias_no_diacritics", "rxcui", "tty", "alias_source", "ingredient_guess"] if col in frame.columns]
            for record in frame[wanted_cols].to_dict("records"):
                rows.append(record)
        if manual_alias_path and Path(manual_alias_path).exists():
            frame = pd.read_csv(manual_alias_path, dtype=str, keep_default_na=False)
            for record in frame.to_dict("records"):
                rows.append(
                    {
                        "alias": record.get("alias", ""),
                        "alias_no_diacritics": normalize_no_diacritics_for_lookup(record.get("alias", "")),
                        "rxcui": record.get("rxcui_hint", ""),
                        "tty": "MANUAL",
                        "alias_source": "manual_drug_alias",
                        "ingredient_guess": record.get("generic_hint", ""),
                    }
                )
        rows.extend(dict(row) for row in alias_rows or [])
        self.aliases_by_first_token = self._build_alias_index(rows)

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        candidates: list[SpanCandidate] = []
        for chunk in context.chunks:
            chunk_tokens = _chunk_lookup_tokens(chunk.text)
            for first_token in chunk_tokens:
                for alias_row in self.aliases_by_first_token.get(first_token, []):
                    alias = str(alias_row["alias"])
                    for start, end in find_phrase_matches(
                        context.raw_text,
                        context.views,
                        alias,
                        chunk=chunk,
                        min_length=self.min_alias_length,
                        require_boundaries=True,
                    ):
                        expanded_start = start
                        expanded_end = self._expand_right_end(context.raw_text, end, chunk)
                        expanded_start, expanded_end = trim_trailing_punctuation(context.raw_text, expanded_start, expanded_end)
                        text = context.raw_text[expanded_start:expanded_end]
                        candidates.append(
                            make_span_candidate(
                                context.raw_text,
                                expanded_start,
                                expanded_end,
                                raw_type="THUỐC",
                                source=self.name,
                                score=0.86 if expanded_end > end else 0.78,
                                chunk=chunk,
                                features={
                                    "alias": alias,
                                    "rxcui": str(alias_row.get("rxcui", "")),
                                    "tty": str(alias_row.get("tty", "")),
                                    "alias_source": str(alias_row.get("alias_source", "")),
                                    "ingredient_guess": str(alias_row.get("ingredient_guess", "")),
                                    "strength": _first_match(_STRENGTH_RE, text),
                                    "route": _first_match(_ROUTE_RE, text),
                                    "frequency": _first_match(_FREQ_RE, text),
                                },
                            )
                        )
        return dedupe_candidates(candidates)

    def _build_alias_index(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        for row in rows:
            alias = str(row.get("alias", "")).strip()
            if not self._valid_alias(alias):
                continue
            tokens = tokenize_for_lookup(alias)
            if not tokens or tokens[0] in _STOP_FIRST_TOKENS or len(tokens[0]) < 3:
                continue
            key = (normalize_no_diacritics_for_lookup(alias), str(row.get("rxcui", "")))
            if key in seen:
                continue
            seen.add(key)
            grouped[tokens[0]].append(dict(row, alias=alias))
        for token, values in grouped.items():
            values.sort(key=lambda item: (-len(str(item.get("alias", ""))), str(item.get("alias", "")).lower()))
            grouped[token] = values[: self.max_aliases_per_first_token]
        return grouped

    def _valid_alias(self, alias: str) -> bool:
        alias = alias.strip()
        if not (self.min_alias_length <= len(alias) <= self.max_alias_length):
            return False
        if alias.replace(".", "").isdigit():
            return False
        return True

    def _expand_right_end(self, raw_text: str, end: int, chunk: Chunk) -> int:
        tail_region = raw_text[end : min(chunk.end, end + 80)]
        match = _TAIL_TOKEN_RE.match(tail_region)
        if not match:
            return end
        return end + match.end()


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(0).strip() if match else ""


def _chunk_lookup_tokens(text: str) -> set[str]:
    """Return lookup tokens plus punctuation-trimmed variants.

    The generic terminology tokenizer intentionally preserves separators such as
    `.` and `/` for medical lookup. For extractor prefiltering, a sentence-final
    token like `atenolol.` must still activate aliases indexed by `atenolol`.
    """

    tokens: set[str] = set()
    for token in tokenize_for_lookup(text):
        tokens.add(token)
        stripped = token.strip(".,;:()[]{}<>\"'")
        if stripped:
            tokens.add(stripped)
    return tokens
