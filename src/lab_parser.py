"""Offset-safe lab parser for structured lab name-result extraction.

The parser implements the architecture described for ``Lab parser`` in
``plans/10_7_26/10_7_architecture.md``: dictionary/NER seeds identify lab
test names, then local composition finds associated results (numeric,
qualitative, range, trend) while preserving raw character offsets. All
exported candidate spans use half-open raw offsets ``[start, end)``.

Key patterns supported:

* ``name: value`` (colon-separated)
* ``name = value unit`` (equals-separated)
* ``name (description): value`` (name with parenthetical alias)
* ``name value reference-range unit`` (whitespace-separated)
* Multiple name-value pairs on the same line (semicolon/comma delimited)
* Table-like rows (bullet items, numbered items)

Since v2 the parser loads a metadata-backed dictionary from
``data_resources/lab_terms_curated.csv`` with canonical grouping from
``data_resources/lab_canonical_map.csv``. Short/ambiguous aliases (e.g.
``K``, ``Ca``, ``Na``, ``cr``) are context-gated via ``requires_context``.
Backward-compatible bare ``Sequence[str]`` input is still accepted.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.models import ClinicalDocument, Line, SpanCandidate
from src.normalization import normalize_for_matching
from src.offset_mapper import OffsetMapper

ENTITY_LAB_NAME = "TÊN_XÉT_NGHIỆM"
ENTITY_LAB_RESULT = "KẾT_QUẢ_XÉT_NGHIỆM"
LAB_SUBSECTION = "LAB_RESULT_SECTION"

SPAN_TRIM_CHARS = " \t\r\n,;:.()[]{}-*•+"
BOUNDARY_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZÀ-ỹ_"

# Expanded unit set covering common chemistry, hematology, endocrine, ABG,
# tumor-marker, and coagulation units observed in PDF-derived dictionary.
LAB_UNITS = (
    r"mg/dl|mmol/l|g/dl|g/l|ng/ml|pg/ml|mcg/dl|μg/dl|μmol/l|"
    r"mEq/l|meq/l|u/l|ui/l|%|đơn\s*vị|unit|units|"
    r"ml|g|mg|mcg|μg|mmol|μmol|mEq|meq|iu|ui|"
    r"fr|mm|cm|mm/h|mmhg|"
    r"iu/l|miu/l|µiu/ml|ng/l|pmol/l|nmol/l|µmol/l|"
    r"fl|pg|coi"
)

# Range/trend operators that appear between two numeric values.
_RANGE_OPS = (
    r"->|-->|→|–|—|-|đến|lên|"
    r"tăng\s*(?:từ\s*)?(?:(?:nhẹ\s*)?lên)?|"
    r"giảm\s*(?:từ\s*)?(?:(?:nhẹ\s*)?xuống)?|"
    r"đạt\s*đỉnh|ổn\s*định\s*ở\s*mức|còn"
)

# Connector/separator words that sit between a lab name and its result.
_CONNECTOR_WORDS = (
    r"là\b|cho\s+thấy\b|ghi\s+nhận\b|trả\s+về\s+là\b|"
    r"kết\s+quả\s+là\b|kết\s+quả\b|có\s+kết\s+quả\b|ở\s+mức\b|"
    r"đo\s+được\b|xác\s+định\b|được\s+cho\s+là\b|"
    r"nâng\s+cao\s+lên\b|cải\s+thiện\s+thành\b"
)

# Qualifier words that describe a trend/direction but are not the result value itself.
_QUALIFIER_WORDS = (
    r"tăng(?:\s*(?:nhẹ|cao|nhiều|hơn|mạnh))?\b|"
    r"giảm(?:\s*(?:nhẹ|nhiều|hơn|mạnh))?\b|"
    r"hạ\b|ổn\s+định\b|"
    r"bắt\s+đầu\s+tăng\b|tiếp\s+tục\s+tăng\b|"
    r"có\s+xu\s+hướng\s+giảm\b|có\s+xu\s+hướng\s+tăng\b|"
    r"đạt\s+đỉnh\b|cao\s+tới\b|thấp\s+tới\b"
)

# Single regex that matches any lab result value expression.
# *Alternation order matters*: range/trend is tried first so that
# ``2.0 -> 3.2`` is captured as one range span, not as the lone numeric ``2.0``.
# Qualitative is tried before numeric so that ``âm tính x1`` is captured
# as qualitative, not 1.
_RESULT_VALUE_RE = re.compile(
    rf"""
    (?:
        # ---- range / trend (longer match – try first) ----
        (?P<range_from>\d+(?:[.,]\d+)?)
        \s*
        (?P<range_op>{_RANGE_OPS})
        \s*
        (?P<range_to>\d+(?:[.,]\d+)?)
        (?:\s*(?P<range_unit>{LAB_UNITS}))?
        |
        # ---- qualitative result ----
        \b(?P<qualitative>
            âm\s*tính|dương\s*tính|bình\s*thường|
            bất\s*thường|không\s*đáng\s*chú\s*ý|
            không\s*có\s*gì\s*đáng\s*chú\s*ý|
            không\s*ghi\s*nhận\s*gì\s*bất\s*thường|
            trong\s*giới\s*hạn\s*bình\s*thường|
            bình\s*thường\s*bình\s*thường
        )
        (?: \s+ x \s* \d+ )?          # optional "x1", "x 1" multiplier suffix
        |
        # ---- simple numeric with optional unit ----
        (?P<numeric_value>\d+(?:[.,]\d+)?)
        \s*
        (?P<numeric_unit>{LAB_UNITS})?
        (?: \s* x \s* \d+ )?          # optional multiplier suffix e.g. "x1"
        |
        # ---- percentage ----
        \d+(?:[.,]\d+)?\s*%
    )
    """,
    re.IGNORECASE | re.UNICODE | re.VERBOSE,
)

# Parenthetical description after a lab name core, e.g. "cea (kháng nguyên ung thư phôi)".
_PAREN_DESCRIPTION_RE = re.compile(
    r"""
    \s*\([^)]*\)\s*
    """,
    re.IGNORECASE | re.UNICODE | re.VERBOSE,
)

LAB_SECTION_MARKERS = (
    "kết quả xét nghiệm", "xét nghiệm", "kết quả phòng thí nghiệm",
    "cận lâm sàng", "laboratory", "kết quả xét nghiệm máu",
)

LAB_LINE_MARKERS = (
    "kết quả", "xét nghiệm", "chỉ số", "nồng độ", "định lượng",
)

# Context gate markers: these marker phrases in the line or its section
# satisfy the context requirement for ambiguous aliases like K, Na, Ca.
_CONTEXT_GATE_LINE_MARKERS = (
    "xét nghiệm", "cận lâm sàng", "kết quả", "điện giải",
    "khí máu", "chem", "cbc", "đông máu", "huyết học",
)

_CONTEXT_GATE_SECTION_KEYWORDS = (
    "cận lâm sàng", "kết quả xét nghiệm", "laboratory",
    "lab_result_section",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LabTermEntry:
    """Metadata-backed dictionary entry from ``lab_terms_curated.csv``.

    Each entry exposes the surface *term* used for text matching plus
    canonical identity, provenance, category/specimen, context-gate flag,
    and matching priority.
    """

    term: str
    canonical_key: str
    canonical_name: str
    source: str
    source_detail: str
    category: str
    specimen: str
    requires_context: bool
    priority: int
    notes: str = ""


@dataclass(frozen=True)
class LabSeed:
    """One lab-name seed before name expansion and result pairing.

    Carries optional ``LabTermEntry`` metadata when sourced from the
    curated dictionary; ``None`` for NER-only seeds.
    """

    start: int
    end: int
    text: str
    seed_source: str          # "lab_dictionary" | "vihealthbert_ner"
    seed_term: str            # original dictionary/alias term
    seed_confidence: float = 1.0
    entry: Optional[LabTermEntry] = None  # metadata when dictionary-backed


@dataclass(frozen=True)
class LabPair:
    """A paired lab name and its detected result."""

    name_start: int
    name_end: int
    name_text: str
    result_start: Optional[int] = None
    result_end: Optional[int] = None
    result_text: Optional[str] = None
    result_kind: str = "unknown"   # "numeric" | "range" | "qualitative"
    unit: Optional[str] = None


@dataclass(frozen=True)
class LabParseTrace:
    """Trace metadata stored in ``SpanCandidate.notes`` for debugging.

    Since v2, carries canonical identity fields from the dictionary
    entry when available.
    """

    rule_id: str
    local_role: str
    dictionary_term: str
    name_span: Tuple[int, int]
    result_span: Optional[Tuple[int, int]]
    result_kind: str
    unit: Optional[str]
    evidence: List[str]
    seed_source: str = "lab_dictionary"
    seed_confidence: float = 1.0
    canonical_key: Optional[str] = None
    canonical_name: Optional[str] = None
    source_detail: Optional[str] = None
    category: Optional[str] = None
    specimen: Optional[str] = None
    requires_context: bool = False


# ---------------------------------------------------------------------------
# Helpers – mirrors of drug_parser utilities
# ---------------------------------------------------------------------------

def _trim_span(raw_text: str, start: int, end: int) -> Tuple[int, int]:
    while start < end and raw_text[start] in SPAN_TRIM_CHARS:
        start += 1
    while end > start and raw_text[end - 1] in SPAN_TRIM_CHARS:
        end -= 1
    return start, end


def _is_word_boundary(raw_text: str, start: int, end: int) -> bool:
    if start > 0 and raw_text[start - 1] in BOUNDARY_CHARS:
        return False
    if end < len(raw_text) and raw_text[end:end + 1] in BOUNDARY_CHARS:
        return False
    return True


def _span_in_line(start: int, end: int, line: Line) -> bool:
    return line.start <= start and end <= line.end


def _unique_terms(terms: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for term in terms:
        key = normalize_for_matching(term)
        if key and key not in seen:
            seen.add(key)
            output.append(term)
    return output


def _line_context(doc: ClinicalDocument, line: Line) -> Tuple[str, str]:
    left_start = max(0, line.start - 80)
    right_end = min(len(doc.raw_text), line.end + 80)
    return doc.raw_text[left_start:line.start], doc.raw_text[line.end:right_end]


# ---------------------------------------------------------------------------
# Dictionary loader  (v2 metadata-backed entry loading)
# ---------------------------------------------------------------------------

def load_lab_dictionary(csv_path: str) -> List[LabTermEntry]:
    """Load ``lab_terms_curated.csv`` into a list of ``LabTermEntry``.

    Returns an empty list if the file cannot be read (e.g. not yet built),
    so the parser degrades gracefully to bare-string usage.
    """
    path = Path(csv_path)
    if not path.exists():
        return []
    entries: List[LabTermEntry] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            term = row.get("term", "")
            if not term:
                continue
            entries.append(LabTermEntry(
                term=term,
                canonical_key=row.get("canonical_key", ""),
                canonical_name=row.get("canonical_name", ""),
                source=row.get("source", ""),
                source_detail=row.get("source_detail", ""),
                category=row.get("category", ""),
                specimen=row.get("specimen", ""),
                requires_context=row.get("requires_context", "false").lower() == "true",
                priority=int(row.get("priority", "0") or "0"),
                notes=row.get("notes", ""),
            ))
    return entries


def build_term_lookup(entries: Sequence[LabTermEntry]) -> Dict[str, LabTermEntry]:
    """Build an alias-lookup dict keyed by *normalized* term string.

    When multiple entries produce the same normalized key, the highest-priority
    entry wins. Ties are broken by longer term text.
    """
    lookup: Dict[str, LabTermEntry] = {}
    for entry in entries:
        key = normalize_for_matching(entry.term)
        if not key:
            continue
        existing = lookup.get(key)
        if existing is None:
            lookup[key] = entry
        else:
            if entry.priority > existing.priority:
                lookup[key] = entry
            elif entry.priority == existing.priority and len(entry.term) > len(existing.term):
                lookup[key] = entry
    return lookup


# ---------------------------------------------------------------------------
# Context gate  (v2 - for requires_context aliases)
# ---------------------------------------------------------------------------

def _has_lab_context(line: Line, doc: ClinicalDocument) -> bool:
    """Check whether the line (or its section) provides lab context.

    Used as a gate for ambiguous aliases with ``requires_context=true``.
    """
    # 1. Check section type / subsection type.
    section_text = (line.section_type or "").lower()
    subsection_text = (line.subsection_type or "").lower()
    combined_sec = section_text + " " + subsection_text
    for kw in _CONTEXT_GATE_SECTION_KEYWORDS:
        if kw in combined_sec:
            return True

    # 2. Check line text for lab markers.
    normalized = normalize_for_matching(line.text)
    for marker in _CONTEXT_GATE_LINE_MARKERS:
        if marker in normalized:
            return True

    # 3. Check left/right context for lab markers.
    left, right = _line_context(doc, line)
    combined = normalize_for_matching(left + " " + right)
    for marker in _CONTEXT_GATE_LINE_MARKERS:
        if marker in combined:
            return True

    return False


# ---------------------------------------------------------------------------
# Overlap resolution  (v2 - prefer longer / more specific alias)
# ---------------------------------------------------------------------------

def resolve_overlapping_aliases(
    aliases: List[str],
    lookup: Dict[str, LabTermEntry],
) -> List[str]:
    """Resolve overlapping alias spans by preferring longer, higher-priority terms.

    Example: if ``bilirubin`` and ``bilirubin toàn phần`` both appear,
    the longer *bilirubin toàn phần* wins when they share the same canonical key.
    """
    if not aliases or not lookup:
        return aliases

    sorted_aliases = sorted(
        aliases,
        key=lambda a: (
            len(a),
            getattr(lookup.get(normalize_for_matching(a)), "priority", 0),
        ),
        reverse=True,
    )

    resolved: List[str] = []
    for alias in sorted_aliases:
        key = normalize_for_matching(alias)
        alias_lower = alias.lower().strip()
        is_subsumed = False
        alias_entry = lookup.get(key)
        for existing in resolved:
            existing_lower = existing.lower().strip()
            existing_key = normalize_for_matching(existing)
            existing_entry = lookup.get(existing_key)
            if alias_lower in existing_lower and len(alias_lower) < len(existing_lower):
                # Subume only if same canonical_key or no entry info.
                if existing_entry and alias_entry:
                    if existing_entry.canonical_key == alias_entry.canonical_key:
                        is_subsumed = True
                        break
                else:
                    is_subsumed = True
                    break
        if not is_subsumed:
            resolved.append(alias)
    return resolved


def _make_dummy_entry(term: str) -> LabTermEntry:
    """Create a minimal entry (priority 0) for bare strings that lack metadata."""
    return LabTermEntry(
        term=term,
        canonical_key=normalize_for_matching(term),
        canonical_name=term,
        source="bare_string",
        source_detail="",
        category="",
        specimen="",
        requires_context=False,
        priority=0,
    )


# ---------------------------------------------------------------------------
# Seed discovery (dictionary + NER)
# ---------------------------------------------------------------------------

def _find_spans_via_normalized(
    doc: ClinicalDocument, term: str,
) -> List[Tuple[int, int]]:
    """Return all raw ``(start, end)`` spans where *term* appears in the doc."""
    mapper = OffsetMapper(
        doc.raw_text,
        doc.normalized_text,
        doc.norm_to_raw_map,
        doc.raw_to_norm_map,
    )
    normalized_term = normalize_for_matching(term)
    if not normalized_term:
        return []

    spans: List[Tuple[int, int]] = []
    cursor = 0
    while True:
        pos = doc.normalized_text.find(normalized_term, cursor)
        if pos == -1:
            break
        raw_span = mapper.recover_raw_span_from_normalized_match(
            pos, pos + len(normalized_term),
        )
        if raw_span is not None:
            raw_start, raw_end = _trim_span(doc.raw_text, raw_span[0], raw_span[1])
            if raw_start < raw_end and _is_word_boundary(doc.raw_text, raw_start, raw_end):
                spans.append((raw_start, raw_end))
        cursor = pos + 1
    return spans


def _dictionary_lab_seeds(
    doc: ClinicalDocument,
    terms: Sequence[str],
    *,
    lookup: Optional[Dict[str, LabTermEntry]] = None,
) -> List[LabSeed]:
    """Create lab-name seeds from curated dictionary terms.

    When *lookup* is provided, each seed is enriched with its
    ``LabTermEntry`` metadata for canonical identity and context gates.
    """
    seeds: List[LabSeed] = []
    for term in _unique_terms(terms):
        entry = None
        if lookup is not None:
            entry = lookup.get(normalize_for_matching(term))
            if entry is None:
                entry = _make_dummy_entry(term)
        for seed_start, seed_end in _find_spans_via_normalized(doc, term):
            seeds.append(
                LabSeed(
                    start=seed_start,
                    end=seed_end,
                    text=doc.raw_text[seed_start:seed_end],
                    seed_source="lab_dictionary",
                    seed_term=term,
                    seed_confidence=1.0,
                    entry=entry,
                )
            )
    return seeds


def _ner_lab_seeds(
    doc: ClinicalDocument,
    ner_candidates: Optional[Sequence[SpanCandidate]],
) -> List[LabSeed]:
    """Convert ViHealthBERT ``TÊN_XÉT_NGHIỆM`` spans into lab-name seeds."""
    if not ner_candidates:
        return []
    seeds: List[LabSeed] = []
    for candidate in ner_candidates:
        if candidate.type_candidate != ENTITY_LAB_NAME:
            continue
        if candidate.file_id != doc.file_id:
            continue
        start, end = _trim_span(doc.raw_text, candidate.start, candidate.end)
        if start >= end:
            continue
        if start < 0 or end > len(doc.raw_text):
            continue
        if doc.raw_text[start:end] != candidate.text.strip(SPAN_TRIM_CHARS):
            continue
        seeds.append(
            LabSeed(
                start=start,
                end=end,
                text=doc.raw_text[start:end],
                seed_source="vihealthbert_ner",
                seed_term=candidate.text,
                seed_confidence=candidate.confidence or 0.75,
            )
        )
    return seeds


def _dedupe_lab_seeds(seeds: Sequence[LabSeed]) -> List[LabSeed]:
    """Prefer dictionary over NER, and resolve overlapping aliases.

    Phase 1: exact-span dedup (dictionary > NER).
    Phase 2: overlap resolution — when a longer seed contains a shorter seed
    and both map to the same canonical_key, keep the longer one.
    """
    # ---- Phase 1: exact-span dedup ----
    source_rank = {"lab_dictionary": 2, "vihealthbert_ner": 1}
    best: Dict[Tuple[int, int], LabSeed] = {}
    for seed in seeds:
        key = (seed.start, seed.end)
        previous = best.get(key)
        if previous is None:
            best[key] = seed
            continue
        prev_rank = source_rank.get(previous.seed_source, 0)
        seed_rank_val = source_rank.get(seed.seed_source, 0)
        if (seed_rank_val, seed.seed_confidence, len(seed.seed_term)) > (
            prev_rank,
            previous.seed_confidence,
            len(previous.seed_term),
        ):
            best[key] = seed

    exact_deduped = sorted(
        best.values(),
        key=lambda item: (item.start, item.end, -item.seed_confidence),
    )

    # ---- Phase 2: overlap resolution (nested aliases from same canonical family) ----
    if len(exact_deduped) <= 1:
        return exact_deduped

    resolved: List[LabSeed] = []
    for seed in exact_deduped:
        is_subsumed = False
        for existing in resolved:
            # If existing contained this seed AND same canonical_key, subsume.
            if existing.start <= seed.start and seed.end <= existing.end:
                if existing.entry and seed.entry:
                    if existing.entry.canonical_key == seed.entry.canonical_key:
                        is_subsumed = True
                        break
                elif len(existing.text) > len(seed.text):
                    # No entry info: prefer longer.
                    is_subsumed = True
                    break
        if not is_subsumed:
            resolved.append(seed)
    return resolved


# ---------------------------------------------------------------------------
# Name expansion  (parenthetical descriptions)
# ---------------------------------------------------------------------------

def _expand_lab_name(
    raw_text: str, name_start: int, name_end: int, line_end: int,
) -> Tuple[int, int]:
    """Expand a lab-name core to include trailing parenthetical alias.

    Example: ``cea`` -> ``cea (kháng nguyên ung thư phôi)``
             ``hct``  -> ``hct (hematocrit)``

    Uses whitespace-only trimming to preserve the closing ``)``.
    """
    cursor = name_end
    match = _PAREN_DESCRIPTION_RE.match(
        raw_text, cursor, min(line_end, cursor + 80),
    )
    if match:
        expanded_start = name_start
        expanded_end = match.end()
        # Whitespace-only trim to keep the closing ')' in the span.
        while expanded_start < expanded_end and raw_text[expanded_start].isspace():
            expanded_start += 1
        while expanded_end > expanded_start and raw_text[expanded_end - 1].isspace():
            expanded_end -= 1
        return expanded_start, expanded_end
    return name_start, name_end


# ---------------------------------------------------------------------------
# Result detection
# ---------------------------------------------------------------------------

def _extract_result_info(
    match: re.Match, raw_text: str,
) -> Tuple[int, int, str, Optional[str]]:
    """Extract (start, end, kind, unit) from a successful ``_RESULT_VALUE_RE`` match."""
    start, end = match.start(), match.end()

    if match.group("range_from"):
        unit = (match.group("range_unit") or "").strip() or None
        return start, end, "range", unit

    if match.group("qualitative"):
        return start, end, "qualitative", None

    if match.group("numeric_value"):
        unit = (match.group("numeric_unit") or "").strip() or None
        # Include the unit suffix (already captured in the match)
        return start, end, "numeric", unit

    # percentage fallback
    if "%" in raw_text[start:end]:
        return start, end, "numeric", "%"

    return start, end, "numeric", None


def _find_all_result_matches(
    raw_text: str, search_start: int, max_end: int,
) -> List[re.Match]:
    """Return every ``_RESULT_VALUE_RE`` match between *search_start* and *max_end*."""
    matches: List[re.Match] = []
    cursor = search_start
    while cursor < max_end:
        m = _RESULT_VALUE_RE.search(raw_text, cursor, max_end)
        if not m:
            break
        matches.append(m)
        cursor = m.end()
    return matches


def _find_result_for_name(
    raw_text: str,
    name_end: int,
    line_end: int,
    *,
    next_seed_start: Optional[int] = None,
) -> Optional[Tuple[int, int, str, Optional[str]]]:
    """Return ``(start, end, kind, unit)`` for the result that follows a lab name.

    The function collects all candidate result matches between the expanded
    name end and the next lab seed (or line end), then prefers:

    1. numeric (exact measurement)
    2. range / trend
    3. qualitative

    This ordering avoids treating a qualifier word like *tăng* as the result
    when a concrete numeric value like *39.2* is present further to the right.
    """
    max_end = min(line_end, next_seed_start) if next_seed_start else line_end
    if name_end >= max_end:
        return None

    matches = _find_all_result_matches(raw_text, name_end, max_end)
    if not matches:
        return None

    # Prefer numeric value over range, range over qualitative.
    for m in matches:
        if m.group("numeric_value"):
            return _extract_result_info(m, raw_text)

    for m in matches:
        if m.group("range_from"):
            return _extract_result_info(m, raw_text)

    for m in matches:
        if m.group("qualitative"):
            return _extract_result_info(m, raw_text)

    # Percentage (captured by the literal % branch in the regex)
    for m in matches:
        if "%" in raw_text[m.start():m.end()]:
            return _extract_result_info(m, raw_text)

    return None


# ---------------------------------------------------------------------------
# Local-role classifier
# ---------------------------------------------------------------------------

def classify_lab_line(line: Line) -> str:
    """Return the local role used as soft evidence for the lab resolver.

    Returns one of:

    * ``lab_subsection_item`` – line inside a detected LAB_RESULT_SECTION
    * ``lab_bullet_item`` – bullet item with lab markers
    * ``lab_numbered_item`` – numbered item with lab markers
    * ``lab_section_header`` – heading-like line with lab markers
    * ``lab_context_line`` – narrative line with lab cue words
    * ``lab_like_line`` – line that structurally resembles a lab result row
    * ``neutral_line`` – no lab evidence
    """
    normalized = normalize_for_matching(line.text)
    stripped = line.text.lstrip()

    if line.subsection_type == LAB_SUBSECTION or line.section_type == LAB_SUBSECTION:
        return "lab_subsection_item"

    if any(marker in normalized for marker in LAB_SECTION_MARKERS):
        if stripped.startswith(("-", "*", "•")):
            return "lab_bullet_item"
        if re.match(r"^\s*\d+[.)]\s+", line.text):
            return "lab_numbered_item"
        return "lab_section_header"

    if any(marker in normalized for marker in LAB_LINE_MARKERS):
        return "lab_context_line"

    # Lines that contain a result-like pattern are structurally lab-like.
    if _RESULT_VALUE_RE.search(line.text):
        return "lab_like_line"

    return "neutral_line"


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------

def _score_lab_name(
    local_role: str,
    has_result: bool,
    result_kind: str,
    seed_source: str = "lab_dictionary",
    seed_confidence: float = 1.0,
) -> Tuple[float, List[str]]:
    """Compute confidence for a ``TÊN_XÉT_NGHIỆM`` candidate."""
    seed_base = {
        "lab_dictionary": 0.70,
        "vihealthbert_ner": 0.66,
    }.get(seed_source, 0.64)
    score = (
        min(seed_base, seed_confidence)
        if seed_source == "vihealthbert_ner"
        else seed_base
    )
    evidence = [seed_source]

    if has_result:
        score += 0.08
        evidence.append("result_paired")
    if result_kind == "numeric":
        score += 0.05
        evidence.append("numeric_result")
    elif result_kind == "range":
        score += 0.04
        evidence.append("range_result")
    elif result_kind == "qualitative":
        score += 0.03
        evidence.append("qualitative_result")

    strong_lab_roles = {
        "lab_subsection_item",
        "lab_bullet_item",
        "lab_numbered_item",
    }
    if local_role in strong_lab_roles:
        score += 0.07
        evidence.append(local_role)
    elif local_role == "lab_section_header":
        score += 0.04
        evidence.append(local_role)
    elif local_role == "lab_context_line":
        score += 0.04
        evidence.append(local_role)
    elif local_role == "lab_like_line":
        score += 0.03
        evidence.append(local_role)

    return round(min(max(score, 0.0), 0.99), 4), evidence


def _score_lab_result(
    local_role: str,
    result_kind: str,
    seed_source: str = "lab_dictionary",
    seed_confidence: float = 1.0,
) -> Tuple[float, List[str]]:
    """Compute confidence for a ``KẾT_QUẢ_XÉT_NGHIỆM`` candidate.

    Results are directly observed values so they start at a higher base
    than names and receive a bonus for being paired with a dictionary seed.
    """
    score = 0.72
    evidence: List[str] = ["direct_observation", "lab_parser"]

    if result_kind == "numeric":
        score += 0.06
        evidence.append("numeric_result")
    elif result_kind == "range":
        score += 0.05
        evidence.append("range_result")
    elif result_kind == "qualitative":
        score += 0.04
        evidence.append("qualitative_result")

    if seed_source == "lab_dictionary":
        score += 0.04
        evidence.append("paired_with_dictionary_name")

    strong_lab_roles = {
        "lab_subsection_item",
        "lab_bullet_item",
        "lab_numbered_item",
    }
    if local_role in strong_lab_roles:
        score += 0.06
        evidence.append(local_role)
    elif local_role in ("lab_section_header", "lab_context_line"):
        score += 0.03
        evidence.append(local_role)
    elif local_role == "lab_like_line":
        score += 0.02
        evidence.append(local_role)

    return round(min(max(score, 0.0), 0.99), 4), evidence


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_lab_candidates(
    doc: ClinicalDocument,
    lab_terms: Sequence[str],
    *,
    ner_candidates: Optional[Sequence[SpanCandidate]] = None,
    lab_entries: Optional[Sequence[LabTermEntry]] = None,
) -> List[SpanCandidate]:
    """Parse lab test names and results from dictionary and optional NER seeds.

    Parameters
    ----------
    doc:
        Offset-preserved clinical document with parsed lines and normalized maps.
    lab_terms:
        Curated lab test name aliases (e.g. from ``lab_seed_terms.csv``).
        Used as primary high-precision seeds.
    ner_candidates:
        Optional ViHealthBERT ``TÊN_XÉT_NGHIỆM`` span candidates. They are
        treated as supplementary seeds for prose/narrative contexts where
        dictionary coverage may be incomplete.
    lab_entries:
        Optional metadata-backed ``LabTermEntry`` entries (e.g. loaded from
        ``lab_terms_curated.csv``). When provided, the function builds a
        normalized-term lookup for canonical identity, context gates, and
        overlap resolution.

    Returns
    -------
    List[SpanCandidate]
        Candidates of type ``TÊN_XÉT_NGHIỆM`` and ``KẾT_QUẢ_XÉT_NGHIỆM``.
        Every candidate satisfies ``doc.raw_text[start:end] == text``.
    """
    # Build the lookup from metadata entries when available.
    lookup: Optional[Dict[str, LabTermEntry]] = None
    if lab_entries is not None:
        lookup = build_term_lookup(lab_entries)

    # ---- seed collection ---------------------------------------------------
    all_seeds: List[LabSeed] = []
    all_seeds.extend(_dictionary_lab_seeds(doc, lab_terms, lookup=lookup))
    all_seeds.extend(_ner_lab_seeds(doc, ner_candidates))
    deduped_seeds = _dedupe_lab_seeds(all_seeds)

    # ---- apply context gates for requires_context aliases ------------------
    gated_seeds: List[LabSeed] = []
    for seed in deduped_seeds:
        if seed.entry and seed.entry.requires_context:
            line = next(
                (item for item in doc.lines
                 if _span_in_line(seed.start, seed.end, item)),
                None,
            )
            if line is not None and not _has_lab_context(line, doc):
                continue  # skip unmatched context-required alias
        gated_seeds.append(seed)

    # ---- group seeds by line -----------------------------------------------
    seeds_by_line: Dict[int, Tuple[Line, List[LabSeed]]] = {}
    for seed in gated_seeds:
        line = next(
            (item for item in doc.lines if _span_in_line(seed.start, seed.end, item)),
            None,
        )
        if line is None:
            continue
        entry_ = seeds_by_line.setdefault(line.line_id, (line, []))
        entry_[1].append(seed)

    candidates: List[SpanCandidate] = []
    seen_keys: set[Tuple[int, int, str]] = set()

    # ---- helper: canonical trace extras from entry -------------------------
    def _entry_trace_kwargs(seed: LabSeed) -> dict:
        if seed.entry is None:
            return {}
        return {
            "canonical_key": seed.entry.canonical_key,
            "canonical_name": seed.entry.canonical_name,
            "source_detail": seed.entry.source_detail,
            "category": seed.entry.category,
            "specimen": seed.entry.specimen,
            "requires_context": seed.entry.requires_context,
        }

    # ---- process each line -------------------------------------------------
    for _line_id, (line, line_seeds) in seeds_by_line.items():
        line_seeds.sort(key=lambda s: (s.start, s.end))
        local_role = classify_lab_line(line)

        for i, seed in enumerate(line_seeds):
            # Expand name to include parenthetical alias/description.
            name_start, name_end = _expand_lab_name(
                doc.raw_text, seed.start, seed.end, line.end,
            )
            name_text = doc.raw_text[name_start:name_end]

            # Boundary: don't scan past the next seed on the same line.
            next_seed_start: Optional[int] = None
            if i + 1 < len(line_seeds):
                next_seed_start = line_seeds[i + 1].start

            # Find associated result value.
            result_info = _find_result_for_name(
                doc.raw_text,
                name_end,
                line.end,
                next_seed_start=next_seed_start,
            )

            left_context, right_context = _line_context(doc, line)

            if result_info is not None:
                result_start, result_end, result_kind, unit = result_info
                result_text = doc.raw_text[result_start:result_end]

                # --- TÊN_XÉT_NGHIỆM candidate ---
                name_key = (name_start, name_end, ENTITY_LAB_NAME)
                if name_key not in seen_keys:
                    seen_keys.add(name_key)
                    name_conf, name_ev = _score_lab_name(
                        local_role, True, result_kind,
                        seed.seed_source, seed.seed_confidence,
                    )
                    name_source = ["lab_parser", seed.seed_source]
                    if local_role != "neutral_line":
                        name_source.append("local_structure")

                    name_trace = LabParseTrace(
                        rule_id="lab_name_seed_plus_result_pairing",
                        local_role=local_role,
                        dictionary_term=seed.seed_term,
                        name_span=(name_start, name_end),
                        result_span=(result_start, result_end),
                        result_kind=result_kind,
                        unit=unit,
                        evidence=name_ev,
                        seed_source=seed.seed_source,
                        seed_confidence=seed.seed_confidence,
                        **_entry_trace_kwargs(seed),
                    )
                    candidates.append(
                        SpanCandidate(
                            file_id=doc.file_id,
                            text=name_text,
                            start=name_start,
                            end=name_end,
                            type_candidate=ENTITY_LAB_NAME,
                            section_type=line.section_type,
                            subsection_type=line.subsection_type,
                            line_id=line.line_id,
                            line_text=line.text,
                            left_context=left_context,
                            right_context=right_context,
                            source=name_source,
                            confidence=name_conf,
                            should_output=True,
                            span_status="candidate",
                            notes=json.dumps(
                                asdict(name_trace), ensure_ascii=False, sort_keys=True,
                            ),
                        )
                    )

                # --- KẾT_QUẢ_XÉT_NGHIỆM candidate ---
                result_key = (result_start, result_end, ENTITY_LAB_RESULT)
                if result_key not in seen_keys:
                    seen_keys.add(result_key)
                    result_conf, result_ev = _score_lab_result(
                        local_role, result_kind,
                        seed.seed_source, seed.seed_confidence,
                    )
                    result_source = ["lab_parser", "result_detection"]
                    if seed.seed_source == "lab_dictionary":
                        result_source.append("paired_with_dictionary_name")
                    if local_role != "neutral_line":
                        result_source.append("local_structure")

                    result_trace = LabParseTrace(
                        rule_id="lab_result_from_name_seed_pairing",
                        local_role=local_role,
                        dictionary_term=seed.seed_term,
                        name_span=(name_start, name_end),
                        result_span=(result_start, result_end),
                        result_kind=result_kind,
                        unit=unit,
                        evidence=result_ev,
                        seed_source=seed.seed_source,
                        seed_confidence=seed.seed_confidence,
                        **_entry_trace_kwargs(seed),
                    )
                    candidates.append(
                        SpanCandidate(
                            file_id=doc.file_id,
                            text=result_text,
                            start=result_start,
                            end=result_end,
                            type_candidate=ENTITY_LAB_RESULT,
                            section_type=line.section_type,
                            subsection_type=line.subsection_type,
                            line_id=line.line_id,
                            line_text=line.text,
                            left_context=left_context,
                            right_context=right_context,
                            source=result_source,
                            confidence=result_conf,
                            should_output=True,
                            span_status="candidate",
                            notes=json.dumps(
                                asdict(result_trace), ensure_ascii=False, sort_keys=True,
                            ),
                        )
                    )
            else:
                # No result – still output the lab name when context supports it.
                name_key = (name_start, name_end, ENTITY_LAB_NAME)
                if name_key not in seen_keys:
                    seen_keys.add(name_key)
                    name_conf, name_ev = _score_lab_name(
                        local_role, False, "unknown",
                        seed.seed_source, seed.seed_confidence,
                    )
                    name_source = ["lab_parser", seed.seed_source]
                    if local_role != "neutral_line":
                        name_source.append("local_structure")

                    name_trace = LabParseTrace(
                        rule_id="lab_name_seed_no_result",
                        local_role=local_role,
                        dictionary_term=seed.seed_term,
                        name_span=(name_start, name_end),
                        result_span=None,
                        result_kind="unknown",
                        unit=None,
                        evidence=name_ev,
                        seed_source=seed.seed_source,
                        seed_confidence=seed.seed_confidence,
                        **_entry_trace_kwargs(seed),
                    )
                    candidates.append(
                        SpanCandidate(
                            file_id=doc.file_id,
                            text=name_text,
                            start=name_start,
                            end=name_end,
                            type_candidate=ENTITY_LAB_NAME,
                            section_type=line.section_type,
                            subsection_type=line.subsection_type,
                            line_id=line.line_id,
                            line_text=line.text,
                            left_context=left_context,
                            right_context=right_context,
                            source=name_source,
                            confidence=name_conf,
                            should_output=True,
                            span_status="candidate",
                            notes=json.dumps(
                                asdict(name_trace), ensure_ascii=False, sort_keys=True,
                            ),
                        )
                    )

    return candidates
