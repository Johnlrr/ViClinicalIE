"""Offset-safe medication parser for structured drug mentions.

The parser implements the architecture described for ``Drug parser`` in
``plans/10_7_26/10_7_architecture.md``: dictionary/NER seeds identify a drug
core, then local composition expands the span to strength, form, route,
frequency and PRN markers while preserving raw character offsets. All exported
candidate spans use half-open raw offsets ``[start, end)``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional, Protocol, Sequence, Tuple

from src.models import ClinicalDocument, Line, SpanCandidate
from src.normalization import normalize_for_matching
from src.offset_mapper import OffsetMapper

ENTITY_DRUG = "THUỐC"
DRUG_SUBSECTIONS = {"MEDICATION_HISTORY", "MEDICATION_ADMINISTERED"}

SPAN_TRIM_CHARS = " \t\r\n,;:.()[]{}-*•+"
BOUNDARY_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZÀ-ỹ_"

STRENGTH_UNITS = r"mg|mcg|μg|ug|g|gram|ml|l|iu|ui|unit|units|đơn vị|%|mg/ml|mg/dl"
ROUTES = r"po|uống|oral|iv|tiêm tĩnh mạch|tm|im|tiêm bắp|sc|sq|dưới da|inh|hít|nebulizer|khí dung|sl|ngậm"
FORMS = r"tablet|tab|viên|capsule|cap|ống|lọ|gói|suspension|sirô|syrup|cream|gel|patch|xl|xr|sr|dr|ec|succinate"
FREQUENCIES = (
    r"bid|tid|qid|qd|qday|daily|hằng ngày|mỗi ngày|ngày\s*\d+\s*lần|"
    r"q\s*\d+\s*h|q\d+h|qam|qpm|qhs|hs|sáng|chiều|tối|"
    r"x\s*\d+(?:\s*lần)?|\d+\s*lần\s*/\s*ngày|mỗi\s+\d+\s+giờ"
)
PRN = r"prn|khi cần|nếu cần"

COMPONENT_TOKEN_PATTERN = re.compile(
    r"(?:\s+|\s*[-/]\s*)"
    r"(?P<token>"
    rf"(?:\d+(?:[,.]\d+)?(?:\s*-\s*\d+(?:[,.]\d+)?)?\s*(?:{STRENGTH_UNITS}))"
    rf"|(?:\d+(?:[,.]\d+)?\s*(?:viên|ống|lọ|gói|ml|giọt))"
    rf"|(?:{ROUTES})"
    rf"|(?:{FORMS})"
    rf"|(?:{FREQUENCIES})"
    rf"|(?:{PRN})"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)

MEDICATION_CONTEXT_MARKERS = (
    "thuốc", "medication", "medications", "toa thuốc", "đơn thuốc", "đang dùng",
    "sử dụng", "uống", "tiêm", "truyền", "trước khi nhập viện",
)

NEGATIVE_DRUG_CONTEXT_MARKERS = (
    "dị ứng", "allergy", "không dung nạp",
)


class DrugLinker(Protocol):
    """Minimal protocol for preliminary RxNorm evidence."""

    def link(self, text: str, top_k: int = 1) -> object:
        """Return an object exposing codes/source/confidence fields."""
        ...


class DrugSeedCatalog(Protocol):
    """Minimal protocol for RxNorm-like seed catalogs."""

    @property
    def entries(self) -> Sequence[object]:
        """RxNorm-like atom entries exposing string and tty attributes."""
        ...


@dataclass(frozen=True)
class DrugCoreSeed:
    """One drug-core seed before medication-boundary composition."""

    start: int
    end: int
    text: str
    seed_source: str
    seed_term: str
    seed_confidence: float = 1.0


@dataclass(frozen=True)
class DrugComponents:
    """Structured components observed inside one medication mention."""

    core_text: str
    core_start: int
    core_end: int
    strength: List[str] = field(default_factory=list)
    dose: List[str] = field(default_factory=list)
    form: List[str] = field(default_factory=list)
    route: List[str] = field(default_factory=list)
    frequency: List[str] = field(default_factory=list)
    prn: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DrugParseTrace:
    """Trace metadata stored in ``SpanCandidate.notes`` for debugging."""

    rule_id: str
    local_role: str
    dictionary_term: str
    core_span: Tuple[int, int]
    expanded_span: Tuple[int, int]
    components: DrugComponents
    evidence: List[str]
    seed_source: str = "drug_dictionary"
    seed_confidence: float = 1.0
    rxnorm_source: Optional[str] = None
    rxnorm_confidence: Optional[float] = None


def _unique_terms(terms: Iterable[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for term in terms:
        key = normalize_for_matching(term)
        if key and key not in seen:
            seen.add(key)
            output.append(term)
    return output


def _rxnorm_catalog_seed_terms(
    doc: ClinicalDocument,
    rxnorm_seed_catalog: Optional[DrugSeedCatalog],
    *,
    max_seed_terms: int = 2000,
) -> List[str]:
    """Return RxNorm ingredient/brand terms that are plausible in this document.

    The full RXNCONSO table is large and contains many clinical-drug strings with
    dose/signature text. For detection seeds we keep only high-value lexical names
    (ingredient/brand/minimal names), require the normalized term to occur in the
    document, and cap the per-document seed count. Curated ``drug_terms`` remain
    the high-precision source; RxNorm catalog seeds are a lower-confidence recall
    fallback.
    """
    if rxnorm_seed_catalog is None:
        return []

    preferred_tty = {"IN", "PIN", "MIN", "BN"}
    seen = set()
    seeds: List[str] = []
    doc_norm = doc.normalized_text or normalize_for_matching(doc.raw_text)
    for entry in getattr(rxnorm_seed_catalog, "entries", []):
        tty = getattr(entry, "tty", "")
        if tty not in preferred_tty:
            continue
        term = getattr(entry, "string", "")
        normalized = normalize_for_matching(term)
        if not normalized or len(normalized) < 4:
            continue
        # Avoid very broad catalog atoms and strings that are unlikely to appear
        # as a compact drug core in Vietnamese notes.
        if len(normalized.split()) > 4:
            continue
        if normalized in seen or normalized not in doc_norm:
            continue
        seen.add(normalized)
        seeds.append(term)
        if len(seeds) >= max_seed_terms:
            break
    return seeds


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


def _normalized_find_spans(doc: ClinicalDocument, term: str) -> List[Tuple[int, int]]:
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
    start = 0
    while True:
        pos = doc.normalized_text.find(normalized_term, start)
        if pos == -1:
            break
        raw_span = mapper.recover_raw_span_from_normalized_match(pos, pos + len(normalized_term))
        if raw_span is not None:
            raw_start, raw_end = _trim_span(doc.raw_text, raw_span[0], raw_span[1])
            if raw_start < raw_end and _is_word_boundary(doc.raw_text, raw_start, raw_end):
                spans.append((raw_start, raw_end))
        start = pos + 1
    return spans


def _dictionary_core_seeds(doc: ClinicalDocument, terms: Sequence[str], seed_source: str, confidence: float) -> List[DrugCoreSeed]:
    seeds: List[DrugCoreSeed] = []
    for term in _unique_terms(terms):
        for core_start, core_end in _normalized_find_spans(doc, term):
            seeds.append(
                DrugCoreSeed(
                    start=core_start,
                    end=core_end,
                    text=doc.raw_text[core_start:core_end],
                    seed_source=seed_source,
                    seed_term=term,
                    seed_confidence=confidence,
                )
            )
    return seeds


def _ner_core_seeds(doc: ClinicalDocument, ner_candidates: Optional[Sequence[SpanCandidate]]) -> List[DrugCoreSeed]:
    """Convert ViHealthBERT THUỐC span candidates into drug-core seeds."""
    if not ner_candidates:
        return []
    seeds: List[DrugCoreSeed] = []
    for candidate in ner_candidates:
        if candidate.type_candidate != ENTITY_DRUG:
            continue
        if candidate.file_id != doc.file_id:
            continue
        start, end = _trim_span(doc.raw_text, candidate.start, candidate.end)
        if start >= end:
            continue
        if start < 0 or end > len(doc.raw_text):
            continue
        if doc.raw_text[start:end] != candidate.text.strip(SPAN_TRIM_CHARS):
            # Keep offset safety strict; a NER candidate with stale text is not a
            # reliable seed for parser expansion.
            continue
        seeds.append(
            DrugCoreSeed(
                start=start,
                end=end,
                text=doc.raw_text[start:end],
                seed_source="vihealthbert_ner",
                seed_term=candidate.text,
                seed_confidence=candidate.confidence or 0.75,
            )
        )
    return seeds


def _dedupe_core_seeds(seeds: Sequence[DrugCoreSeed]) -> List[DrugCoreSeed]:
    """Prefer curated dictionary > NER > RxNorm catalog for identical core spans."""
    priority = {"drug_dictionary": 3, "vihealthbert_ner": 2, "rxnorm_catalog": 1}
    best: dict[Tuple[int, int], DrugCoreSeed] = {}
    for seed in seeds:
        key = (seed.start, seed.end)
        previous = best.get(key)
        if previous is None:
            best[key] = seed
            continue
        prev_rank = priority.get(previous.seed_source, 0)
        seed_rank = priority.get(seed.seed_source, 0)
        if (seed_rank, seed.seed_confidence, len(seed.seed_term)) > (prev_rank, previous.seed_confidence, len(previous.seed_term)):
            best[key] = seed
    return sorted(best.values(), key=lambda item: (item.start, item.end, -item.seed_confidence))


def classify_medication_line(line: Line) -> str:
    """Return the local role used as soft evidence for the drug resolver."""
    normalized = normalize_for_matching(line.text)
    stripped = line.text.lstrip()

    if line.subsection_type in DRUG_SUBSECTIONS or line.section_type in DRUG_SUBSECTIONS:
        return "medication_subsection_item"
    if any(marker in normalized for marker in NEGATIVE_DRUG_CONTEXT_MARKERS):
        return "negative_medication_context"
    if stripped.startswith(("-", "*", "•")) and any(marker in normalized for marker in MEDICATION_CONTEXT_MARKERS):
        return "medication_bullet_item"
    if re.match(r"^\s*\d+[.)]\s+", line.text) and any(marker in normalized for marker in MEDICATION_CONTEXT_MARKERS):
        return "medication_numbered_item"
    if any(marker in normalized for marker in MEDICATION_CONTEXT_MARKERS):
        return "medication_context_line"
    if COMPONENT_TOKEN_PATTERN.search(line.text):
        return "medication_like_line"
    return "neutral_line"


def _component_bucket(token: str) -> str:
    normalized = normalize_for_matching(token)
    if re.fullmatch(rf"(?:{ROUTES})", normalized, flags=re.IGNORECASE):
        return "route"
    if re.fullmatch(rf"(?:{FREQUENCIES})", normalized, flags=re.IGNORECASE):
        return "frequency"
    if re.fullmatch(rf"(?:{PRN})", normalized, flags=re.IGNORECASE):
        return "prn"
    if re.fullmatch(rf"(?:{FORMS})", normalized, flags=re.IGNORECASE):
        return "form"
    if re.search(rf"\b(?:{STRENGTH_UNITS})\b", normalized, flags=re.IGNORECASE):
        return "strength"
    return "dose"


def compose_medication_boundary(
    raw_text: str,
    core_start: int,
    core_end: int,
    line_end: int,
    *,
    max_extension_chars: int = 96,
) -> Tuple[int, int, DrugComponents]:
    """Expand a drug core to a full medication mention within the same line."""
    cursor = core_end
    max_end = min(line_end, core_end + max_extension_chars)
    buckets = {
        "strength": [],
        "dose": [],
        "form": [],
        "route": [],
        "frequency": [],
        "prn": [],
    }

    while cursor < max_end:
        # Stop before separators that usually introduce another entity/list item.
        next_char = raw_text[cursor:cursor + 1]
        if next_char in ";\n\r":
            break
        match = COMPONENT_TOKEN_PATTERN.match(raw_text, cursor, max_end)
        if not match:
            break
        token = match.group("token").strip()
        if not token:
            break
        bucket = _component_bucket(token)
        buckets[bucket].append(token)
        cursor = match.end()

    start, end = _trim_span(raw_text, core_start, cursor)
    components = DrugComponents(
        core_text=raw_text[core_start:core_end],
        core_start=core_start,
        core_end=core_end,
        strength=buckets["strength"],
        dose=buckets["dose"],
        form=buckets["form"],
        route=buckets["route"],
        frequency=buckets["frequency"],
        prn=buckets["prn"],
    )
    return start, end, components


def _score_candidate(
    local_role: str,
    components: DrugComponents,
    has_rxnorm: bool,
    seed_source: str = "drug_dictionary",
    seed_confidence: float = 1.0,
) -> Tuple[float, List[str]]:
    seed_base = {
        "drug_dictionary": 0.72,
        "vihealthbert_ner": 0.68,
        "rxnorm_catalog": 0.66,
    }.get(seed_source, 0.64)
    score = min(seed_base, seed_confidence) if seed_source == "vihealthbert_ner" else seed_base
    evidence = [seed_source]

    if components.strength or components.dose:
        score += 0.07
        evidence.append("dose_or_strength_pattern")
    if components.route:
        score += 0.05
        evidence.append("route_marker")
    if components.frequency or components.prn:
        score += 0.05
        evidence.append("frequency_or_prn_marker")
    strong_medication_roles = {
        "medication_subsection_item",
        "medication_bullet_item",
        "medication_numbered_item",
        "medication_context_line",
    }
    if local_role in strong_medication_roles:
        score += 0.07
        evidence.append(local_role)
    elif local_role == "negative_medication_context":
        score -= 0.10
        evidence.append(local_role)
    elif local_role == "medication_like_line":
        score += 0.03
        evidence.append(local_role)
    if has_rxnorm:
        score += 0.06
        evidence.append("rxnorm_prelink")

    return round(min(max(score, 0.0), 0.99), 4), evidence


def _line_context(doc: ClinicalDocument, line: Line) -> Tuple[str, str]:
    left_start = max(0, line.start - 80)
    right_end = min(len(doc.raw_text), line.end + 80)
    return doc.raw_text[left_start:line.start], doc.raw_text[line.end:right_end]


def parse_drug_candidates(
    doc: ClinicalDocument,
    drug_terms: Sequence[str],
    *,
    linker: Optional[DrugLinker] = None,
    top_k: int = 1,
    rxnorm_seed_catalog: Optional[DrugSeedCatalog] = None,
    rxnorm_seed_terms: Optional[Sequence[str]] = None,
    ner_candidates: Optional[Sequence[SpanCandidate]] = None,
) -> List[SpanCandidate]:
    """Parse medication mentions from dictionary/RxNorm/NER seeds.

    Parameters
    ----------
    doc:
        Offset-preserved clinical document with parsed lines and normalized maps.
    drug_terms:
        Curated aliases used as primary core seeds. Since [#alias-expansion]
        the ``drug_aliases.csv`` includes all RxNorm IN/PIN/MIN/BN atoms, so
        ``rxnorm_seed_catalog`` and ``rxnorm_seed_terms`` are retained only for
        backward-compatibility and are now secondary to the expanded dictionary.
    linker:
        Optional preliminary RxNorm linker. Its evidence raises confidence and
        populates ``mapping_candidates`` but is not a hard requirement.
    top_k:
        Number of RxNorm candidates to request from the linker.
    rxnorm_seed_catalog:
        Deprecated. Full RxNorm catalog – now redundant because ``drug_terms``
        already contains all RxNorm IN/PIN/MIN/BN names. Kept for API compat.
    rxnorm_seed_terms:
        Deprecated. Precomputed RxNorm terms – now redundant. Kept for API compat.
    ner_candidates:
        Optional ViHealthBERT ``THUỐC`` span candidates. They are treated as
        parser seeds and expanded with the same boundary composer.
    """
    all_seeds: List[DrugCoreSeed] = []
    all_seeds.extend(_dictionary_core_seeds(doc, drug_terms, "drug_dictionary", 1.0))
    # rxnorm_seed_catalog / rxnorm_seed_terms are now redundant because
    # drug_aliases.csv already includes all RxNorm IN/PIN/MIN/BN atoms.
    # We keep a minimal fallback for backward compatibility only.
    catalog_terms = list(rxnorm_seed_terms or [])
    catalog_terms.extend(_rxnorm_catalog_seed_terms(doc, rxnorm_seed_catalog))
    if catalog_terms:
        all_seeds.extend(_dictionary_core_seeds(doc, catalog_terms, "rxnorm_catalog", 0.82))
    all_seeds.extend(_ner_core_seeds(doc, ner_candidates))

    candidates: List[SpanCandidate] = []
    seen_candidates: set[Tuple[int, int, str]] = set()
    for seed in _dedupe_core_seeds(all_seeds):
            core_start, core_end = seed.start, seed.end
            line = next((item for item in doc.lines if _span_in_line(core_start, core_end, item)), None)
            if line is None:
                continue

            span_start, span_end, components = compose_medication_boundary(
                doc.raw_text,
                core_start,
                core_end,
                line.end,
            )
            if span_start >= span_end:
                continue

            text = doc.raw_text[span_start:span_end]
            if doc.raw_text[span_start:span_end] != text:
                continue

            rxnorm_codes: List[str] = []
            rxnorm_source: Optional[str] = None
            rxnorm_confidence: Optional[float] = None
            if linker is not None:
                result = linker.link(text, top_k=top_k)
                rxnorm_codes = list(getattr(result, "codes", []) or [])
                rxnorm_source = getattr(result, "source", None)
                rxnorm_confidence = getattr(result, "confidence", None)

            local_role = classify_medication_line(line)
            confidence, evidence = _score_candidate(
                local_role,
                components,
                bool(rxnorm_codes),
                seed.seed_source,
                seed.seed_confidence,
            )
            source = ["drug_parser", seed.seed_source, "boundary_composition"]
            if components.strength or components.dose or components.route or components.frequency or components.prn:
                source.append("dose_parser")
            if local_role != "neutral_line":
                source.append("local_structure")
            if rxnorm_codes:
                source.append("rxnorm_prelink")

            candidate_key = (span_start, span_end, ENTITY_DRUG)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)

            trace = DrugParseTrace(
                rule_id="drug_core_seed_plus_medication_composition",
                local_role=local_role,
                dictionary_term=seed.seed_term,
                core_span=(core_start, core_end),
                expanded_span=(span_start, span_end),
                components=components,
                evidence=evidence,
                seed_source=seed.seed_source,
                seed_confidence=seed.seed_confidence,
                rxnorm_source=rxnorm_source,
                rxnorm_confidence=rxnorm_confidence,
            )
            left_context, right_context = _line_context(doc, line)
            candidates.append(
                SpanCandidate(
                    file_id=doc.file_id,
                    text=text,
                    start=span_start,
                    end=span_end,
                    type_candidate=ENTITY_DRUG,
                    section_type=line.section_type,
                    subsection_type=line.subsection_type,
                    line_id=line.line_id,
                    line_text=line.text,
                    left_context=left_context,
                    right_context=right_context,
                    source=source,
                    confidence=confidence,
                    mapping_candidates=rxnorm_codes,
                    should_output=True,
                    span_status="candidate",
                    notes=json.dumps(asdict(trace), ensure_ascii=False, sort_keys=True),
                )
            )

    return candidates
