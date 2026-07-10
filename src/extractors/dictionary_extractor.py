from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_types import SpanCandidate
from src.extractors.base import BaseExtractor, ExtractionContext
from src.extractors.utils import dedupe_candidates, find_phrase_matches, make_span_candidate
from src.linking.terminology_normalizer import normalize_for_lookup


class DictionaryExtractor(BaseExtractor):
    name = "dictionary"

    def __init__(
        self,
        *,
        dictionary_paths: Sequence[str | Path] | None = None,
        entries: Sequence[Mapping[str, Any]] | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.config = dict(config or {})
        self.min_alias_length = int(self.config.get("min_alias_length", 3))
        self.max_alias_length = int(self.config.get("max_alias_length", 80))
        rows: list[dict[str, Any]] = []
        for path in dictionary_paths or []:
            path_obj = Path(path)
            if path_obj.exists():
                frame = pd.read_csv(path_obj, dtype=str, keep_default_na=False)
                for record in frame.to_dict("records"):
                    record["dictionary_path"] = str(path_obj)
                    rows.append(record)
        rows.extend(dict(entry) for entry in entries or [])
        self.entries = [row for row in rows if self._valid_alias(str(row.get("alias", "")))]

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        candidates: list[SpanCandidate] = []
        for chunk in context.chunks:
            for entry in self.entries:
                alias = str(entry.get("alias", ""))
                raw_type = str(entry.get("raw_type") or entry.get("type") or "").strip() or None
                for start, end in find_phrase_matches(
                    context.raw_text,
                    context.views,
                    alias,
                    chunk=chunk,
                    min_length=self.min_alias_length,
                    require_boundaries=True,
                ):
                    if not self._accept_match(context.raw_text[start:end], alias):
                        continue
                    candidates.append(
                        make_span_candidate(
                            context.raw_text,
                            start,
                            end,
                            raw_type=raw_type,
                            source="dictionary",
                            score=0.70,
                            chunk=chunk,
                            features={
                                "alias": alias,
                                "canonical": entry.get("canonical", ""),
                                "dictionary_path": entry.get("dictionary_path", "inline"),
                            },
                        )
                    )
        return dedupe_candidates(candidates)

    def _valid_alias(self, alias: str) -> bool:
        alias = alias.strip()
        return self.min_alias_length <= len(alias) <= self.max_alias_length

    def _accept_match(self, matched_text: str, alias: str) -> bool:
        """Avoid accent-insensitive false positives for very short Vietnamese aliases.

        For example, `phù` and `phụ` both normalize to `phu` without
        diacritics. Matching such short aliases accent-insensitively creates
        obvious false positives, so require an exact diacritic-preserving lookup
        match for aliases up to three characters that contain Vietnamese marks.
        """

        if len(alias.strip()) <= 3 and normalize_for_lookup(alias) != normalize_for_lookup(matched_text):
            return False
        return True
