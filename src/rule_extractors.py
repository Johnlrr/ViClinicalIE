"""Rule-based span extractors for V0 clinical concept candidates."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.models import ClinicalDocument, Line, SpanCandidate
from src.normalization import normalize_for_matching
from src.offset_mapper import OffsetMapper


ENTITY_LAB_NAME = "TÊN_XÉT_NGHIỆM"
ENTITY_LAB_RESULT = "KẾT_QUẢ_XÉT_NGHIỆM"
ENTITY_DRUG = "THUỐC"
ENTITY_DIAGNOSIS = "CHẨN_ĐOÁN"
ENTITY_SYMPTOM = "TRIỆU_CHỨNG"
ENTITY_NON_TARGET = "NON_TARGET"

TARGET_ENTITY_TYPES = {
    ENTITY_LAB_NAME,
    ENTITY_LAB_RESULT,
    ENTITY_DRUG,
    ENTITY_DIAGNOSIS,
    ENTITY_SYMPTOM,
}

LAB_SUBSECTIONS = {"LAB_RESULT_SECTION"}
DRUG_SUBSECTIONS = {"MEDICATION_HISTORY", "MEDICATION_ADMINISTERED"}
DIAGNOSIS_SUBSECTIONS = {
    "CHRONIC_DISEASES",
    "DIAGNOSTIC_FINDINGS",
    "LAB_RESULT_SECTION",
    "IMAGING_RESULT_SECTION",
}
DIAGNOSIS_SECTIONS = {"PAST_HISTORY", "HOSPITAL_ASSESSMENT"}
SYMPTOM_SUBSECTIONS = {
    "ADMISSION_REASON",
    "CURRENT_SYMPTOMS",
    "SYMPTOM_DETAIL",
    "IMMEDIATE_PRE_ADMISSION_STATUS",
}

VALUE_PATTERN = re.compile(
    r"(?P<value>"
    r"[<>]?\d+(?:[,.]\d+)?(?:\s*(?:mg/dl|mg/l|mmol/l|g/dl|k/uL|u/l|%|x\s*10\^?\d+/\w+))?"
    r"|âm tính|dương tính|bình thường|tăng nhẹ|tăng|giảm|đang chờ"
    r")",
    re.IGNORECASE,
)

DOSE_TRAIL_PATTERN = re.compile(
    r"(?:\s+|)"
    r"(?:(?:\d+(?:[,.]\d+)?(?:-\d+(?:[,.]\d+)?)?\s*(?:mg|mcg|g|gram|ml|mg/ml|iu|unit))"
    r"|(?:po|iv|im|sc|bid|tid|qid|daily|q\d+h|qam|qhs|prn|nebulizer|oral|x\s*\d+)"
    r"|(?:succinate|xl|xr|sr|dr|ec|suspension|tablet|capsule))",
    re.IGNORECASE,
)

SPAN_TRIM_CHARS = " \t\r\n,;:.()[]{}-*•+"
BOUNDARY_LEFT = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZÀ-ỹ_"
BOUNDARY_RIGHT = BOUNDARY_LEFT


def read_term_csv(path: str) -> List[str]:
    """Read one-term-per-row CSV resources, ignoring comments and empty rows."""
    terms: List[str] = []
    resource_path = Path(path)
    if not resource_path.exists():
        return terms

    with resource_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            term = row[0].strip()
            if not term or term.startswith("#") or term.lower() == "term":
                continue
            terms.append(term)
    return terms


def unique_terms(terms: Iterable[str]) -> List[str]:
    """Normalize duplicate term resources while preserving original spelling."""
    seen = set()
    output: List[str] = []
    for term in terms:
        key = normalize_for_matching(term)
        if key and key not in seen:
            seen.add(key)
            output.append(term)
    return output


def line_context(line: Line) -> Tuple[str, str]:
    """Return left/right context placeholders for V0 line-level extraction."""
    return "", ""


def trim_span(raw_text: str, start: int, end: int) -> Tuple[int, int]:
    """Trim punctuation and whitespace from a raw span."""
    while start < end and raw_text[start] in SPAN_TRIM_CHARS:
        start += 1
    while end > start and raw_text[end - 1] in SPAN_TRIM_CHARS:
        end -= 1
    return start, end


def is_word_boundary(raw_text: str, start: int, end: int) -> bool:
    """Avoid matching terms inside alphanumeric words when terms are normal words."""
    if start > 0 and raw_text[start - 1] in BOUNDARY_LEFT:
        return False
    if end < len(raw_text) and raw_text[end:end + 1] in BOUNDARY_RIGHT:
        return False
    return True


def make_candidate(
    doc: ClinicalDocument,
    line: Line,
    start: int,
    end: int,
    entity_type: str,
    source: Sequence[str],
    confidence: float,
    should_output: bool = True,
    reject_reason: Optional[str] = None,
) -> Optional[SpanCandidate]:
    """Create a validated SpanCandidate from raw offsets."""
    start, end = trim_span(doc.raw_text, start, end)
    if start >= end:
        return None

    text = doc.raw_text[start:end]
    if doc.raw_text[start:end] != text:
        return None

    left_context, right_context = line_context(line)
    return SpanCandidate(
        file_id=doc.file_id,
        text=text,
        start=start,
        end=end,
        type_candidate=entity_type,
        section_type=line.section_type,
        subsection_type=line.subsection_type,
        line_id=line.line_id,
        line_text=line.text,
        left_context=left_context,
        right_context=right_context,
        source=list(source),
        confidence=confidence,
        should_output=should_output,
        span_status="candidate" if should_output else "rejected",
        reject_reason=reject_reason,
    )


def normalized_find_spans(doc: ClinicalDocument, term: str) -> List[Tuple[int, int]]:
    """Find all normalized term occurrences and recover raw spans."""
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
        norm_end = pos + len(normalized_term)
        raw_span = mapper.recover_raw_span_from_normalized_match(pos, norm_end)
        if raw_span is not None:
            raw_start, raw_end = trim_span(doc.raw_text, raw_span[0], raw_span[1])
            if raw_start < raw_end and is_word_boundary(doc.raw_text, raw_start, raw_end):
                spans.append((raw_start, raw_end))
        start = pos + 1
    return spans


def span_in_line(start: int, end: int, line: Line) -> bool:
    """Check whether a raw span is fully inside a parsed line."""
    return line.start <= start and end <= line.end


def line_value_raw_span(line: Line) -> Optional[Tuple[int, int]]:
    """Return raw offsets for the value part of a key-value line."""
    if line.key is None or line.value is None:
        return None
    colon_pos = line.text.find(":")
    if colon_pos == -1:
        return None
    value_start_in_line = colon_pos + 1
    while value_start_in_line < len(line.text) and line.text[value_start_in_line].isspace():
        value_start_in_line += 1
    value_end_in_line = len(line.text)
    while value_end_in_line > value_start_in_line and line.text[value_end_in_line - 1].isspace():
        value_end_in_line -= 1
    return line.start + value_start_in_line, line.start + value_end_in_line


def value_or_line_span(line: Line) -> Tuple[int, int]:
    """Prefer the value span for key-value lines, otherwise use the full line."""
    value_span = line_value_raw_span(line)
    if value_span and value_span[0] < value_span[1]:
        return value_span
    return line.start, line.end


def extend_drug_span(raw_text: str, start: int, end: int, line_end: int) -> Tuple[int, int]:
    """Extend a drug seed to include nearby strength, route, form, and frequency."""
    cursor = end
    max_end = min(line_end, end + 80)
    while cursor < max_end:
        match = DOSE_TRAIL_PATTERN.match(raw_text, cursor, max_end)
        if not match:
            break
        token = match.group(0)
        if not token.strip():
            break
        cursor = match.end()
    return trim_span(raw_text, start, cursor)


def extract_lab_candidates(doc: ClinicalDocument, lab_terms: Sequence[str]) -> List[SpanCandidate]:
    """Extract lab test names and lab result values."""
    candidates: List[SpanCandidate] = []
    normalized_terms = [(term, normalize_for_matching(term)) for term in unique_terms(lab_terms)]

    for line in doc.lines:
        in_lab_context = line.subsection_type in LAB_SUBSECTIONS or line.section_type in LAB_SUBSECTIONS
        normalized_line = normalize_for_matching(line.text)
        matched_terms = [
            term for term, norm_term in normalized_terms
            if norm_term and norm_term in normalized_line
        ]
        if not matched_terms:
            continue

        if not in_lab_context and not any(marker in normalized_line for marker in ("xét nghiệm", "laboratory", "cbc")):
            continue

        for term in matched_terms:
            for test_start, test_end in normalized_find_spans(doc, term):
                if not span_in_line(test_start, test_end, line):
                    continue
                value_search_start = test_end
                value_search_end = min(line.end, test_end + 80)
                value_match = VALUE_PATTERN.search(doc.raw_text, value_search_start, value_search_end)
                if not value_match:
                    continue

                test_candidate = make_candidate(
                    doc,
                    line,
                    test_start,
                    test_end,
                    ENTITY_LAB_NAME,
                    ["lab_regex", "lab_dictionary"],
                    0.86,
                )
                value_candidate = make_candidate(
                    doc,
                    line,
                    value_match.start("value"),
                    value_match.end("value"),
                    ENTITY_LAB_RESULT,
                    ["lab_regex"],
                    0.84,
                )
                if test_candidate:
                    candidates.append(test_candidate)
                if value_candidate:
                    candidates.append(value_candidate)

    return candidates


def extract_drug_candidates(doc: ClinicalDocument, drug_terms: Sequence[str]) -> List[SpanCandidate]:
    """Extract drug names and nearby dosage/frequency text."""
    candidates: List[SpanCandidate] = []
    for term in unique_terms(drug_terms):
        for raw_start, raw_end in normalized_find_spans(doc, term):
            line = next((candidate_line for candidate_line in doc.lines if span_in_line(raw_start, raw_end, candidate_line)), None)
            if line is None:
                continue
            span_start, span_end = extend_drug_span(doc.raw_text, raw_start, raw_end, line.end)
            confidence = 0.90 if line.subsection_type in DRUG_SUBSECTIONS else 0.78
            candidate = make_candidate(
                doc,
                line,
                span_start,
                span_end,
                ENTITY_DRUG,
                ["drug_dictionary", "dose_parser"],
                confidence,
            )
            if candidate:
                candidates.append(candidate)
    return candidates


def reject_non_target_candidates(doc: ClinicalDocument, non_target_terms: Sequence[str]) -> List[SpanCandidate]:
    """Record obvious procedure/imaging terms as rejected internal candidates."""
    candidates: List[SpanCandidate] = []
    for term in unique_terms(non_target_terms):
        for raw_start, raw_end in normalized_find_spans(doc, term):
            line = next((candidate_line for candidate_line in doc.lines if span_in_line(raw_start, raw_end, candidate_line)), None)
            if line is None:
                continue
            candidate = make_candidate(
                doc,
                line,
                raw_start,
                raw_end,
                ENTITY_NON_TARGET,
                ["non_target_dictionary"],
                0.95,
                should_output=False,
                reject_reason="procedure_or_imaging_method",
            )
            if candidate:
                candidates.append(candidate)
    return candidates


def diagnosis_search_window(line: Line, raw_text: str) -> Tuple[int, int]:
    """Limit diagnosis extraction to likely finding text."""
    start, end = value_or_line_span(line)
    window = raw_text[start:end]
    normalized = normalize_for_matching(window)
    for trigger in ("cho thấy", "ghi nhận", "phát hiện", "kết luận", "là"):
        pos = normalized.find(trigger)
        if pos != -1:
            trigger_raw_start = start + window.lower().find(trigger)
            if trigger_raw_start >= start:
                return min(end, trigger_raw_start + len(trigger)), end
    return start, end


def extract_diagnosis_candidates(
    doc: ClinicalDocument,
    diagnosis_terms: Sequence[str],
    non_target_terms: Sequence[str],
) -> List[SpanCandidate]:
    """Extract diagnosis candidates from history and finding contexts."""
    candidates: List[SpanCandidate] = []
    non_target_norms = [normalize_for_matching(term) for term in non_target_terms]

    for term in unique_terms(diagnosis_terms):
        for raw_start, raw_end in normalized_find_spans(doc, term):
            line = next((candidate_line for candidate_line in doc.lines if span_in_line(raw_start, raw_end, candidate_line)), None)
            if line is None:
                continue
            window_start, window_end = diagnosis_search_window(line, doc.raw_text)
            if not (window_start <= raw_start and raw_end <= window_end):
                continue

            normalized_text = normalize_for_matching(doc.raw_text[raw_start:raw_end])
            if any(normalized_text == non_target for non_target in non_target_norms):
                continue

            strong_context = (
                line.subsection_type in DIAGNOSIS_SUBSECTIONS
                or line.section_type in DIAGNOSIS_SECTIONS
            )
            if not strong_context and line.line_kind not in {"bullet", "key_value"}:
                continue

            candidate = make_candidate(
                doc,
                line,
                raw_start,
                raw_end,
                ENTITY_DIAGNOSIS,
                ["diagnosis_dictionary", "section_rule"],
                0.86 if strong_context else 0.72,
            )
            if candidate:
                candidates.append(candidate)
    return candidates


def expand_symptom_span(raw_text: str, start: int, end: int, line: Line) -> Tuple[int, int]:
    """Expand common symptom spans to include anatomical/timing qualifiers."""
    max_end = min(line.end, end + 60)
    phrase = raw_text[end:max_end]
    match = re.match(
        r"(?:\s+(?:vùng|khi|về|âm ỉ|nhẹ|nặng|thoáng qua|kéo dài|hạ sườn|trước tim|ra máu|lượng ít|đỏ tươi|từng đợt)[^,.;]*)",
        phrase,
        re.IGNORECASE,
    )
    if match:
        end = end + match.end()
    return trim_span(raw_text, start, end)


def extract_symptom_candidates(doc: ClinicalDocument, symptom_terms: Sequence[str]) -> List[SpanCandidate]:
    """Extract symptom candidates from current-history sections."""
    candidates: List[SpanCandidate] = []
    for term in unique_terms(symptom_terms):
        for raw_start, raw_end in normalized_find_spans(doc, term):
            line = next((candidate_line for candidate_line in doc.lines if span_in_line(raw_start, raw_end, candidate_line)), None)
            if line is None:
                continue
            in_symptom_context = line.subsection_type in SYMPTOM_SUBSECTIONS
            if not in_symptom_context and line.section_type != "CURRENT_HISTORY":
                continue
            span_start, span_end = expand_symptom_span(doc.raw_text, raw_start, raw_end, line)
            candidate = make_candidate(
                doc,
                line,
                span_start,
                span_end,
                ENTITY_SYMPTOM,
                ["symptom_dictionary", "section_rule"],
                0.84 if in_symptom_context else 0.70,
            )
            if candidate:
                candidates.append(candidate)
    return candidates


def dedupe_candidates(candidates: Iterable[SpanCandidate]) -> List[SpanCandidate]:
    """Remove exact duplicate candidates while preserving order."""
    seen = set()
    output: List[SpanCandidate] = []
    for candidate in candidates:
        key = (candidate.file_id, candidate.start, candidate.end, candidate.type_candidate)
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output


def validate_candidate_offsets(documents_by_id: Dict[str, ClinicalDocument], candidates: Iterable[SpanCandidate]) -> List[SpanCandidate]:
    """Keep candidates whose raw offsets exactly match their text."""
    valid: List[SpanCandidate] = []
    for candidate in candidates:
        doc = documents_by_id.get(candidate.file_id)
        if doc is None:
            continue
        if 0 <= candidate.start < candidate.end <= len(doc.raw_text) and doc.raw_text[candidate.start:candidate.end] == candidate.text:
            valid.append(candidate)
    return valid


def candidate_to_json(candidate: SpanCandidate) -> Dict[str, object]:
    """Serialize a SpanCandidate to the V0 JSONL schema."""
    data = asdict(candidate)
    return data


def write_span_candidates_jsonl(candidates: Iterable[SpanCandidate], path: str) -> None:
    """Write span candidates as UTF-8 JSON Lines."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for candidate in candidates:
            f.write(json.dumps(candidate_to_json(candidate), ensure_ascii=False) + "\n")


def extraction_summary(candidates: Sequence[SpanCandidate], documents: Sequence[ClinicalDocument]) -> Dict[str, object]:
    """Build a compact summary for logging and tests."""
    output_candidates = [candidate for candidate in candidates if candidate.should_output]
    by_type = Counter(candidate.type_candidate for candidate in output_candidates)
    rejected = Counter(candidate.reject_reason for candidate in candidates if not candidate.should_output)
    files_with_output = {candidate.file_id for candidate in output_candidates}
    return {
        "total_candidates": len(candidates),
        "output_candidates": len(output_candidates),
        "by_type": dict(by_type),
        "rejected": dict(rejected),
        "empty_output_files": sorted(doc.file_id for doc in documents if doc.file_id not in files_with_output),
    }
