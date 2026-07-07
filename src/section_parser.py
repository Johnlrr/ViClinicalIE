"""Section and line parser for semi-structured clinical notes."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from src.models import ClinicalDocument, Line, Section
from src.normalization import normalize_for_matching


MAIN_SECTION_TYPES = {"PAST_HISTORY", "CURRENT_HISTORY", "HOSPITAL_ASSESSMENT"}

DEFAULT_PARENT_BY_SECTION = {
    "CHRONIC_DISEASES": "PAST_HISTORY",
    "MEDICATION_HISTORY": "PAST_HISTORY",
    "RISK_FACTORS": "PAST_HISTORY",
    "ADMISSION_REASON": "CURRENT_HISTORY",
    "CURRENT_SYMPTOMS": "CURRENT_HISTORY",
    "SYMPTOM_DETAIL": "CURRENT_HISTORY",
    "PRE_ADMISSION_EVENTS": "CURRENT_HISTORY",
    "IMMEDIATE_PRE_ADMISSION_STATUS": "CURRENT_HISTORY",
    "DIAGNOSTIC_FINDINGS": "HOSPITAL_ASSESSMENT",
    "LAB_RESULT_SECTION": "HOSPITAL_ASSESSMENT",
    "IMAGING_RESULT_SECTION": "HOSPITAL_ASSESSMENT",
    "PROCEDURE_SECTION": "HOSPITAL_ASSESSMENT",
    "MEDICATION_ADMINISTERED": "HOSPITAL_ASSESSMENT",
}


SECTION_ALIASES: Dict[str, List[str]] = {
    "PAST_HISTORY": [
        "tiền sử bệnh",
        "tiền sử bệnh nội khoa",
        "tiền sử bệnh lý",
        "tiền sử phẫu thuật",
        "tiền sử phẫu thuật / thủ thuật",
    ],
    "CHRONIC_DISEASES": [
        "các bệnh mãn tính",
        "các bệnh lý mãn tính",
        "các bệnh lý mạn tính",
        "bệnh mãn tính",
        "bệnh lý mãn tính",
        "bệnh lý mạn tính",
        "các bệnh lý nội khoa mạn tính",
    ],
    "CURRENT_HISTORY": [
        "tiền sử bệnh hiện tại",
        "tiền sử bệnh bệnh hiện tại",
        "bệnh sử hiện tại",
        "bệnh sử hin tại",
        "bệnh sử",
        "lịch sử bệnh hiện tại",
    ],
    "HOSPITAL_ASSESSMENT": [
        "đánh giá tại bệnh viện",
        "kết quả khám tại bệnh viện",
        "khám tại bệnh viện",
        "cận lâm sàng",
    ],
    "CURRENT_SYMPTOMS": [
        "triệu chứng hiện tại",
        "các triệu chứng hiện tại",
        "triệu chứng khi nhập viện",
        "triệu chứng chính",
        "dấu hiệu lâm sàng",
    ],
    "SYMPTOM_DETAIL": [
        "đặc điểm triệu chứng",
        "đặc điểm của triệu chứng",
        "đặc điểm triệu chứng khi khám tại khoa cấp cứu",
        "diễn biến bệnh",
        "diễn biến",
    ],
    "PRE_ADMISSION_EVENTS": [
        "các sự kiện trước khi nhập viện",
        "sự kiện trước khi nhập viện",
        "các diễn biến trước khi nhập viện",
        "diễn biến trước khi nhập viện",
        "các biến trước khi nhập viện",
    ],
    "IMMEDIATE_PRE_ADMISSION_STATUS": [
        "tình trạng ngay trước khi nhập viện",
        "tình trạng trước nhập viện",
        "tình trạng lúc vào viện",
    ],
    "LAB_RESULT_SECTION": [
        "kết quả xét nghiệm",
        "kết quả xét nghiệm máu",
        "kết quả phòng thí nghiệm",
        "kết quả laboratory",
        "xét nghiệm",
    ],
    "IMAGING_RESULT_SECTION": [
        "kết quả chẩn đoán hình ảnh",
        "kết quả hình ảnh",
        "kết quả chụp ảnh",
        "kết quả chụp ảnh/kỹ thuật chẩn đoán hình ảnh",
        "chẩn đoán hình ảnh và thăm dò",
        "chẩn đoán hình ảnh",
    ],
    "PROCEDURE_SECTION": [
        "các thủ thuật đã thực hiện",
        "thủ thuật đã thực hiện",
        "thủ thuật thực hiện",
        "các thủ thuật thực hiện",
        "thủ thuật được thực hiện",
    ],
    "MEDICATION_HISTORY": [
        "thuốc trước khi nhập viện",
        "thuốc trước khi nhập viện lần này",
        "thuốc đã dùng trước đây",
        "bệnh nhân có tiền sử dụng thuốc",
    ],
    "MEDICATION_ADMINISTERED": [
        "các thuốc đã thực hiện",
        "được cho dùng",
        "được chỉ định điều trị",
        "dùng tại khoa cấp cứu",
    ],
    "ADMISSION_REASON": [
        "lý do nhập viện",
        "thời điểm khởi phát triệu chứng",
        "khởi phát bệnh",
    ],
    "RISK_FACTORS": [
        "các yếu tố nguy cơ liên quan",
        "yếu tố nguy cơ liên quan",
        "dị ứng",
    ],
    "DIAGNOSTIC_FINDINGS": [
        "các phát hiện chẩn đoán khác",
        "các kết quả chẩn đoán khác",
        "kết quả khám lâm sàng",
    ],
}


_NORMALIZED_ALIAS_ROWS: List[Tuple[str, str]] = sorted(
    (
        (section_type, normalize_for_matching(alias))
        for section_type, aliases in SECTION_ALIASES.items()
        for alias in aliases
    ),
    key=lambda item: len(item[1]),
    reverse=True,
)


def strip_line_prefix(text: str) -> Tuple[str, int]:
    """Remove numbering/bullet prefixes and return cleaned text plus offset delta."""
    leading_len = len(text) - len(text.lstrip())
    stripped = text.lstrip()
    punctuation_match = re.match(r"^[.。]+\s*", stripped)
    punctuation_len = punctuation_match.end() if punctuation_match else 0
    if punctuation_len:
        stripped = stripped[punctuation_len:]
    prefix_match = re.match(r"(?:(?:[-*•+]\s*)|(?:\d+\.\s*))+", stripped)
    if prefix_match:
        return stripped[prefix_match.end():].strip(), leading_len + punctuation_len + prefix_match.end()
    return stripped.strip(), leading_len + punctuation_len


def split_key_value(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a short key-value line at the first colon."""
    if ":" not in text:
        return None, None
    key, value = text.split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key or len(key) > 80:
        return None, None
    return key, value


def classify_header_text(text: str) -> Optional[Tuple[str, str]]:
    """
    Classify cleaned header text.

    Returns ``(section_type, matched_alias)``. Longest alias wins, which prevents
    `tiền sử bệnh hiện tại` from being swallowed by the shorter `tiền sử bệnh`.
    """
    normalized = normalize_for_matching(text.strip().strip(":"))
    if not normalized:
        return None

    for section_type, alias in _NORMALIZED_ALIAS_ROWS:
        if normalized == alias:
            return section_type, alias
        if normalized.startswith(alias):
            next_char_index = len(alias)
            if next_char_index == len(normalized) or normalized[next_char_index].isspace():
                return section_type, alias
            if alias.endswith("hiện tại") and normalized[next_char_index:next_char_index + 4] in {"bệnh", "benh"}:
                return section_type, alias
    return None


def display_header_text(cleaned_text: str, matched_alias: str) -> str:
    """Return a clean display header, trimming content glued after the alias."""
    normalized = normalize_for_matching(cleaned_text.strip().strip(":"))
    if normalized == matched_alias:
        return cleaned_text.strip().strip(":")
    if normalized.startswith(matched_alias):
        return cleaned_text[:len(matched_alias)].strip().strip(":")
    return cleaned_text.strip().strip(":")


def iter_raw_lines(raw_text: str) -> Iterable[Tuple[int, str, int, int]]:
    """Yield line_id, line text without newline, raw start, raw end."""
    offset = 0
    for line_id, line_with_newline in enumerate(raw_text.splitlines(keepends=True), start=1):
        line_text = line_with_newline.rstrip("\r\n")
        line_start = offset
        line_end = line_start + len(line_text)
        yield line_id, line_text, line_start, line_end
        offset += len(line_with_newline)

    if raw_text and not raw_text.endswith(("\n", "\r")):
        return
    if raw_text == "":
        return


def classify_line(raw_line: str) -> Tuple[str, Optional[str], Optional[str], Optional[Tuple[str, str]], int]:
    """
    Classify one raw line.

    Returns ``(line_kind, key, value, header_match, header_delta)``.
    """
    cleaned, delta = strip_line_prefix(raw_line)
    if not cleaned:
        return "free_text", None, None, None, delta

    key, value = split_key_value(cleaned)
    if key is not None:
        header_match = classify_header_text(key)
        if header_match:
            return "key_value", key, value, header_match, delta
        return "key_value", key, value, None, delta

    header_match = classify_header_text(cleaned)
    if header_match and len(cleaned.split()) <= 12:
        section_type, _ = header_match
        line_kind = "header" if section_type in MAIN_SECTION_TYPES else "subheader"
        return line_kind, None, None, header_match, delta

    stripped = raw_line.lstrip()
    if stripped.startswith(("-", "*", "•", "+")):
        return "bullet", None, None, None, delta

    return "free_text", None, None, None, delta


def parse_document_sections(doc: ClinicalDocument) -> ClinicalDocument:
    """Parse sections and line inventory for one document in-place."""
    sections: List[Section] = []
    lines: List[Line] = []
    current_main: Optional[str] = None
    current_sub: Optional[str] = None

    for line_id, raw_line, line_start, line_end in iter_raw_lines(doc.raw_text):
        line_kind, key, value, header_match, header_delta = classify_line(raw_line)

        if header_match:
            section_type, matched_alias = header_match
            if section_type in MAIN_SECTION_TYPES:
                current_main = section_type
                current_sub = None
                level = 1
                parent = None
            else:
                current_sub = section_type
                level = 2
                parent = current_main or DEFAULT_PARENT_BY_SECTION.get(section_type)
                if current_main is None and parent in MAIN_SECTION_TYPES:
                    current_main = parent

            cleaned_header = key if key is not None else strip_line_prefix(raw_line)[0]
            header_text = display_header_text(cleaned_header, matched_alias)
            header_start = line_start + header_delta
            header_end = min(header_start + len(header_text), line_end)
            sections.append(
                Section(
                    section_type=section_type,
                    text=header_text,
                    start=header_start,
                    end=header_end,
                    level=level,
                    parent_section_type=parent,
                    confidence=1.0,
                    line_id=line_id,
                    alias_source=matched_alias,
                )
            )

        line_section = current_main
        line_subsection = current_sub
        if header_match and header_match[0] in MAIN_SECTION_TYPES:
            line_section = header_match[0]
            line_subsection = None
        elif header_match:
            line_subsection = header_match[0]
            line_section = current_main or DEFAULT_PARENT_BY_SECTION.get(header_match[0])

        lines.append(
            Line(
                text=raw_line,
                start=line_start,
                end=line_end,
                line_kind=line_kind,
                line_id=line_id,
                key=key,
                value=value,
                section_type=line_section,
                subsection_type=line_subsection,
            )
        )

    doc.sections = sections
    doc.lines = lines
    doc.metadata["detected_main_sections"] = sorted(
        {
            main_type
            for section in sections
            for main_type in (section.section_type, section.parent_section_type)
            if main_type in MAIN_SECTION_TYPES
        }
    )
    doc.metadata["has_numbered_sections"] = any(re.match(r"^\s*\d+\.", line.text) for line in lines)
    return doc


def parse_documents(documents: Iterable[ClinicalDocument]) -> List[ClinicalDocument]:
    """Parse all documents and return them as a list."""
    return [parse_document_sections(doc) for doc in documents]


def write_section_aliases(path: str) -> None:
    """Write clean section aliases to JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(SECTION_ALIASES, f, ensure_ascii=False, indent=2)


def export_section_inventory(documents: Iterable[ClinicalDocument], path: str) -> None:
    """Export parsed section headers to CSV."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "file_id",
        "section_text",
        "section_type",
        "parent_section_type",
        "level",
        "start",
        "end",
        "line_id",
        "confidence",
        "alias_source",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for doc in documents:
            for section in doc.sections:
                writer.writerow(
                    {
                        "file_id": f"{doc.file_id}.txt",
                        "section_text": section.text,
                        "section_type": section.section_type,
                        "parent_section_type": section.parent_section_type or "",
                        "level": section.level,
                        "start": section.start,
                        "end": section.end,
                        "line_id": section.line_id,
                        "confidence": section.confidence,
                        "alias_source": section.alias_source or "",
                    }
                )


def export_line_inventory(documents: Iterable[ClinicalDocument], path: str) -> None:
    """Export parsed line inventory to CSV."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "file_id",
        "line_id",
        "line_text",
        "line_start",
        "line_end",
        "section_type",
        "subsection_type",
        "line_kind",
        "key",
        "value",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for doc in documents:
            for line in doc.lines:
                writer.writerow(
                    {
                        "file_id": f"{doc.file_id}.txt",
                        "line_id": line.line_id,
                        "line_text": line.text,
                        "line_start": line.start,
                        "line_end": line.end,
                        "section_type": line.section_type or "",
                        "subsection_type": line.subsection_type or "",
                        "line_kind": line.line_kind,
                        "key": line.key or "",
                        "value": line.value or "",
                    }
                )
