from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.data_types import Chunk
from src.linking.terminology_normalizer import normalize_for_lookup, normalize_no_diacritics_for_lookup


SECTION_LABELS: set[str] = {
    "PAST_HISTORY",
    "PAST_MEDICAL_HISTORY",
    "PRE_ADMISSION_MEDICATION",
    "CURRENT_ILLNESS",
    "ADMISSION_REASON",
    "CURRENT_SYMPTOM",
    "SYMPTOM_CHARACTERISTIC",
    "PRE_ADMISSION_EVENT",
    "HOSPITAL_ASSESSMENT",
    "PHYSICAL_EXAM",
    "LAB_RESULT",
    "IMAGING_RESULT",
    "PROCEDURE",
    "TREATMENT",
    "DIAGNOSIS_FINDING",
    "UNKNOWN",
}


DEFAULT_SECTION_CONFIG: dict[str, Any] = {
    "default_section": "UNKNOWN",
    "heading_max_chars": 160,
    "min_heading_confidence": 0.55,
    "carry_forward_section": True,
    "detect_inline_headings": True,
    "inline_heading_max_prefix_chars": 80,
    "carried_confidence": 0.30,
}

_LEADING_MARKER_RE = re.compile(
    r"^\s*(?:(?:[-*•]+)\s*|(?:(?:\d+|[ivxlcdm]+|[a-zA-Z])[.)])\s+)",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class SectionMatch:
    label: str
    confidence: float
    source: str
    matched_text: str
    is_heading: bool


class SectionDetector:
    def __init__(self, patterns: Mapping[str, list[str]], config: Mapping[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_SECTION_CONFIG, **dict(config or {})}
        self.default_section = str(self.config.get("default_section", "UNKNOWN"))
        if self.default_section not in SECTION_LABELS:
            raise ValueError(f"Invalid default section: {self.default_section}")
        self.patterns = _compile_patterns(patterns)

    def detect_chunk_section(self, chunk: Chunk) -> SectionMatch | None:
        text = chunk.text.strip()
        if not text:
            return None
        max_chars = int(self.config.get("heading_max_chars", 160))
        detect_inline = bool(self.config.get("detect_inline_headings", True))
        inline_prefix_chars = int(self.config.get("inline_heading_max_prefix_chars", 80))

        normalized = _strip_leading_marker(normalize_for_lookup(text))
        normalized_no_diac = _strip_leading_marker(normalize_no_diacritics_for_lookup(text))
        is_short = len(text) <= max_chars
        heading_like = _is_heading_like(text, max_chars)

        match = self._match_exact_or_contained(
            normalized,
            normalized_no_diac,
            is_short=is_short,
            heading_like=heading_like,
            allow_containment=False,
        )
        if match is not None:
            return match

        if detect_inline and ":" in text:
            prefix = text.split(":", 1)[0][:inline_prefix_chars]
            prefix_norm = _strip_leading_marker(normalize_for_lookup(prefix))
            prefix_no_diac = _strip_leading_marker(normalize_no_diacritics_for_lookup(prefix))
            match = self._match_exact_or_contained(
                prefix_norm,
                prefix_no_diac,
                is_short=True,
                heading_like=True,
                inline=True,
                allow_containment=True,
            )
            if match is not None:
                return match

        match = self._match_exact_or_contained(
            normalized,
            normalized_no_diac,
            is_short=is_short,
            heading_like=heading_like,
            allow_containment=True,
        )
        if match is not None:
            return match

        return None

    def apply(self, chunks: list[Chunk]) -> list[Chunk]:
        current_section = self.default_section
        current_confidence = 0.0
        carried_confidence = float(self.config.get("carried_confidence", 0.30))
        carry_forward = bool(self.config.get("carry_forward_section", True))

        for chunk in chunks:
            match = self.detect_chunk_section(chunk)
            if match is not None and match.confidence >= float(self.config.get("min_heading_confidence", 0.55)):
                current_section = match.label
                current_confidence = match.confidence
                chunk.section = match.label
                chunk.section_confidence = match.confidence
                chunk.section_source = match.source
                if match.is_heading and _is_unknown_subsection_candidate(chunk.text):
                    chunk.subsection = normalize_for_lookup(chunk.text)
                continue

            if carry_forward and current_section != self.default_section:
                chunk.section = current_section
                chunk.section_confidence = min(current_confidence, carried_confidence)
                chunk.section_source = "carry_forward"
            else:
                chunk.section = self.default_section
                chunk.section_confidence = 0.0
                chunk.section_source = "default"

            if chunk.subsection is None and _is_unknown_subsection_candidate(chunk.text):
                chunk.subsection = normalize_for_lookup(chunk.text)

        return chunks

    def _match_exact_or_contained(
        self,
        normalized: str,
        normalized_no_diac: str,
        *,
        is_short: bool,
        heading_like: bool,
        inline: bool = False,
        allow_containment: bool = True,
    ) -> SectionMatch | None:
        best: SectionMatch | None = None
        for label, pattern_rows in self.patterns.items():
            for pattern in pattern_rows:
                pattern_norm = pattern["norm"]
                pattern_no_diac = pattern["no_diac"]
                source_suffix = "inline" if inline else "heading"
                candidate: SectionMatch | None = None
                if normalized == pattern_norm:
                    candidate = SectionMatch(label, 1.0, f"exact_{source_suffix}", pattern["raw"], True)
                elif normalized_no_diac == pattern_no_diac:
                    candidate = SectionMatch(label, 0.90, f"exact_no_diacritics_{source_suffix}", pattern["raw"], True)
                elif allow_containment and (heading_like or inline) and _starts_or_contains_heading(normalized, pattern_norm):
                    candidate = SectionMatch(label, 0.82 if inline else 0.78, f"containment_{source_suffix}", pattern["raw"], True)
                elif allow_containment and is_short and _starts_or_contains_heading(normalized_no_diac, pattern_no_diac):
                    candidate = SectionMatch(label, 0.72, f"containment_no_diacritics_{source_suffix}", pattern["raw"], True)

                if candidate is not None and (best is None or candidate.confidence > best.confidence):
                    best = candidate
        return best


def load_section_patterns(path: str | Path) -> dict[str, list[str]]:
    pattern_path = Path(path)
    with pattern_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Section patterns file must contain a mapping: {pattern_path}")
    patterns: dict[str, list[str]] = {}
    for label, values in data.items():
        if label not in SECTION_LABELS:
            raise ValueError(f"Unknown section label in {pattern_path}: {label}")
        if not isinstance(values, list):
            raise ValueError(f"Patterns for {label} must be a list")
        patterns[label] = [str(value) for value in values if str(value).strip()]
    return patterns


def detect_sections(
    chunks: list[Chunk],
    patterns: Mapping[str, list[str]],
    config: Mapping[str, Any] | None = None,
) -> list[Chunk]:
    return SectionDetector(patterns, config).apply(chunks)


def _compile_patterns(patterns: Mapping[str, list[str]]) -> dict[str, list[dict[str, str]]]:
    compiled: dict[str, list[dict[str, str]]] = {}
    for label, values in patterns.items():
        if label not in SECTION_LABELS:
            raise ValueError(f"Unknown section label: {label}")
        compiled[label] = []
        for value in values:
            raw = str(value).strip()
            if not raw:
                continue
            compiled[label].append(
                {
                    "raw": raw,
                    "norm": _strip_leading_marker(normalize_for_lookup(raw)),
                    "no_diac": _strip_leading_marker(normalize_no_diacritics_for_lookup(raw)),
                }
            )
    return compiled


def _strip_leading_marker(text: str) -> str:
    return _LEADING_MARKER_RE.sub("", text).strip()


def _starts_or_contains_heading(text: str, pattern: str) -> bool:
    if not pattern:
        return False
    if text.startswith(pattern):
        return True
    prefix = text.split(":", 1)[0].strip()
    if prefix.startswith(pattern):
        return True
    # Do not match arbitrary mid-sentence occurrences such as
    # "được điều trị bằng..." as a TREATMENT heading. Section detection should
    # be a high-precision prior; entity/assertion modules can inspect content.
    return False


def _is_heading_like(text: str, max_chars: int) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > max_chars:
        return False
    if _LEADING_MARKER_RE.match(stripped):
        return True
    if ":" in stripped and stripped.index(":") <= min(80, max_chars):
        return True
    if stripped.isupper() and len(stripped.split()) <= 12:
        return True
    return len(stripped.split()) <= 10


def _is_unknown_subsection_candidate(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    return bool(":" in stripped or _LEADING_MARKER_RE.match(stripped))
