"""Rule-based assertion detection for V0 clinical span candidates."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.models import ClinicalDocument, Line, SpanCandidate
from src.normalization import normalize_for_matching
from src.rule_extractors import (
    ENTITY_DIAGNOSIS,
    ENTITY_DRUG,
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_SYMPTOM,
)


ASSERTION_TYPES = {ENTITY_DIAGNOSIS, ENTITY_DRUG, ENTITY_SYMPTOM}
LAB_TYPES = {ENTITY_LAB_NAME, ENTITY_LAB_RESULT}
ALLOWED_ASSERTIONS = {"isNegated", "isHistorical", "isFamily"}
ASSERTION_ORDER = ["isNegated", "isHistorical", "isFamily"]

NEGATION_TRIGGERS = [
    "không ghi nhận",
    "không phát hiện",
    "không thấy",
    "không có",
    "phủ nhận",
    "loại trừ",
    "không",
    "chưa",
]
RIGHT_NEGATION_TRIGGERS = ["âm tính"]

HISTORICAL_TRIGGERS = [
    "thuốc trước khi nhập viện",
    "bệnh lý mãn tính",
    "bệnh lý mạn tính",
    "bệnh mãn tính",
    "bệnh mạn tính",
    "tiền sử",
    "trước đây",
    "đã từng",
    "từng bị",
    "mạn tính",
    "mãn tính",
    "đã điều trị",
    "đã sử dụng",
    "đã ngừng",
]

FAMILY_TERMS = [
    "nhiều thành viên trong gia đình",
    "thành viên trong gia đình",
    "người trong gia đình",
    "người thân",
    "người nhà",
    "họ hàng",
    "gia đình",
    "con trai",
    "con gái",
    "anh trai",
    "chị gái",
    "em trai",
    "em gái",
    "bố",
    "ba",
    "cha",
    "mẹ",
]
FAMILY_RELATION_TRIGGERS = ["chẩn đoán", "tiền sử", "mắc", "bị", "có"]
FAMILY_NARRATOR_PATTERNS = [
    "người nhà kể",
    "người nhà nhận thấy",
    "gia đình nhận thấy",
    "gia đình lo ngại",
    "con trai phát hiện",
    "con gái phát hiện",
    "theo lời người nhà",
    "theo lời gia đình",
    "được con trai phát hiện",
    "được con gái phát hiện",
]

SCOPE_BREAK_MARKERS = [".", ";", "\n", " nhưng ", " tuy nhiên ", " song "]


def _norm(text: str) -> str:
    """Normalize text for trigger matching."""
    return normalize_for_matching(text)


def _unique_ordered(assertions: Iterable[str]) -> List[str]:
    """Return allowed assertions in stable output order."""
    found = set(assertions)
    return [assertion for assertion in ASSERTION_ORDER if assertion in found]


def _append_source(source: Sequence[str], marker: str) -> List[str]:
    """Append a source marker without duplicating it."""
    output = list(source)
    if marker not in output:
        output.append(marker)
    return output


def _candidate_line(doc: ClinicalDocument, candidate: SpanCandidate) -> Optional[Line]:
    """Find the parsed line containing a candidate."""
    if candidate.line_id is not None:
        for line in doc.lines:
            if line.line_id == candidate.line_id and line.start <= candidate.start and candidate.end <= line.end:
                return line
    for line in doc.lines:
        if line.start <= candidate.start and candidate.end <= line.end:
            return line
    return None


def _line_bounds(doc: ClinicalDocument, candidate: SpanCandidate) -> Tuple[int, int]:
    """Return raw line bounds for a candidate; fall back to the full document."""
    line = _candidate_line(doc, candidate)
    if line is None:
        return 0, len(doc.raw_text)
    return line.start, line.end


def _last_scope_break(text: str) -> int:
    """Return the last break marker start within text, or -1."""
    lower = text.lower()
    return max(lower.rfind(marker) for marker in SCOPE_BREAK_MARKERS)


def _first_scope_break(text: str) -> int:
    """Return the first break marker start within text, or len(text)."""
    lower = text.lower()
    positions = [lower.find(marker) for marker in SCOPE_BREAK_MARKERS]
    positions = [position for position in positions if position >= 0]
    return min(positions) if positions else len(text)


def _left_scope(doc: ClinicalDocument, candidate: SpanCandidate) -> str:
    """Text before candidate in the same assertion scope."""
    line_start, _ = _line_bounds(doc, candidate)
    left = doc.raw_text[line_start:candidate.start]
    break_at = _last_scope_break(left)
    if break_at >= 0:
        return left[break_at + 1 :]
    return left


def _right_scope(doc: ClinicalDocument, candidate: SpanCandidate, limit: int = 60) -> str:
    """Text after candidate in the same assertion scope."""
    _, line_end = _line_bounds(doc, candidate)
    right = doc.raw_text[candidate.end : min(line_end, candidate.end + limit)]
    return right[: _first_scope_break(right)]


def _line_scope(doc: ClinicalDocument, candidate: SpanCandidate) -> str:
    """Full parsed line text for candidate-level context checks."""
    line_start, line_end = _line_bounds(doc, candidate)
    return doc.raw_text[line_start:line_end]


def is_negated(candidate: SpanCandidate, doc: ClinicalDocument) -> bool:
    """Detect negation in the same sentence/bullet scope."""
    if candidate.type_candidate not in ASSERTION_TYPES:
        return False

    left = _norm(_left_scope(doc, candidate))
    if any(_norm(trigger) in left for trigger in NEGATION_TRIGGERS):
        return True

    right = _norm(_right_scope(doc, candidate, limit=40))
    return any(_norm(trigger) in right for trigger in RIGHT_NEGATION_TRIGGERS)


def _has_historical_prior(candidate: SpanCandidate) -> bool:
    """Use section/subsection priors for historical context."""
    if candidate.type_candidate not in ASSERTION_TYPES:
        return False
    if candidate.type_candidate == ENTITY_DRUG and candidate.subsection_type == "MEDICATION_HISTORY":
        return True
    if candidate.type_candidate == ENTITY_DIAGNOSIS and candidate.subsection_type == "CHRONIC_DISEASES":
        return True
    return candidate.section_type == "PAST_HISTORY"


def is_historical(candidate: SpanCandidate, doc: ClinicalDocument) -> bool:
    """Detect historical context from section priors and explicit triggers."""
    if candidate.type_candidate not in ASSERTION_TYPES:
        return False
    if _has_historical_prior(candidate):
        return True

    line_scope = _norm(_line_scope(doc, candidate))
    left_scope = _norm(_left_scope(doc, candidate))
    return any(_norm(trigger) in line_scope or _norm(trigger) in left_scope for trigger in HISTORICAL_TRIGGERS)


def _looks_like_family_narrator(before_candidate: str) -> bool:
    """Reject family mentions that only identify a narrator/observer."""
    for pattern in FAMILY_NARRATOR_PATTERNS:
        position = before_candidate.rfind(_norm(pattern))
        if position >= 0 and "bệnh nhân" in before_candidate[position:]:
            return True
    return False


def is_family(candidate: SpanCandidate, doc: ClinicalDocument) -> bool:
    """Detect strict family-history patterns before the entity."""
    if candidate.type_candidate not in {ENTITY_DIAGNOSIS, ENTITY_SYMPTOM}:
        return False

    line_start, _ = _line_bounds(doc, candidate)
    before_candidate = _norm(doc.raw_text[line_start:candidate.start])
    if _looks_like_family_narrator(before_candidate):
        return False

    for family_term in FAMILY_TERMS:
        family_pos = before_candidate.rfind(_norm(family_term))
        if family_pos < 0:
            continue
        relation_window = before_candidate[family_pos + len(_norm(family_term)) :]
        if any(_norm(trigger) in relation_window for trigger in FAMILY_RELATION_TRIGGERS):
            return True
    return False


def infer_time_context(candidate: SpanCandidate, assertions: Sequence[str]) -> str:
    """Infer coarse time context used by downstream review/debugging."""
    if "isHistorical" in assertions:
        return "past"
    if candidate.section_type == "HOSPITAL_ASSESSMENT":
        return "in_hospital"
    if candidate.subsection_type == "PRE_ADMISSION_EVENTS":
        return "recent_past"
    if candidate.section_type == "CURRENT_HISTORY":
        return "current"
    return candidate.time_context or "unknown"


def add_assertions(
    candidates: Iterable[SpanCandidate],
    documents_by_id: Dict[str, ClinicalDocument],
) -> List[SpanCandidate]:
    """Return span candidates with V0 assertion candidates populated."""
    asserted: List[SpanCandidate] = []
    for candidate in candidates:
        doc = documents_by_id.get(candidate.file_id)
        if doc is None or candidate.type_candidate in LAB_TYPES or candidate.type_candidate not in ASSERTION_TYPES:
            asserted.append(
                replace(
                    candidate,
                    assertion_candidates=[],
                    time_context=infer_time_context(candidate, []),
                )
            )
            continue

        assertions: List[str] = list(candidate.assertion_candidates)
        source = list(candidate.source)
        notes = candidate.notes

        if is_negated(candidate, doc):
            assertions.append("isNegated")
            source = _append_source(source, "assertion_negation_rule")
        if is_historical(candidate, doc):
            assertions.append("isHistorical")
            source = _append_source(source, "assertion_historical_rule")
        if is_family(candidate, doc):
            assertions.append("isFamily")
            source = _append_source(source, "assertion_family_rule")

        ordered_assertions = _unique_ordered(assertions)
        asserted.append(
            replace(
                candidate,
                assertion_candidates=ordered_assertions,
                time_context=infer_time_context(candidate, ordered_assertions),
                source=source,
                notes=notes,
            )
        )
    return asserted
