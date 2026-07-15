from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from streamlit_app.data_loader import get_position


TYPE_COLORS = {
    "TRIỆU_CHỨNG": "#DBEAFE",
    "CHẨN_ĐOÁN": "#FDE68A",
    "THUỐC": "#DCFCE7",
    "TÊN_XÉT_NGHIỆM": "#E9D5FF",
    "KẾT_QUẢ_XÉT_NGHIỆM": "#FED7AA",
}

SOURCE_COLORS = {
    "gold": "#BBF7D0",
    "prediction": "#BFDBFE",
    "tp": "#86EFAC",
    "fp": "#FECACA",
    "fn": "#FDBA74",
    "span_mismatch": "#DDD6FE",
    "type_mismatch": "#FEF08A",
    "assertion_mismatch": "#FBCFE8",
    "candidate_mismatch": "#CFFAFE",
    "live": "#E0E7FF",
}


@dataclass(slots=True)
class HighlightSpan:
    start: int
    end: int
    label: str
    source: str = "prediction"
    title: str = ""


def spans_from_records(records: list[dict[str, Any]], *, source: str) -> list[HighlightSpan]:
    spans: list[HighlightSpan] = []
    for record in records:
        start, end = get_position(record)
        if end <= start:
            continue
        entity_type = str(record.get("type", ""))
        label = f"{source}: {entity_type}"
        title = f"{record.get('text', '')} | {entity_type} | {start}:{end}"
        spans.append(HighlightSpan(start=start, end=end, label=label, source=source, title=title))
    return spans


def spans_from_error_rows(rows: list[dict[str, Any]], *, source: str) -> list[HighlightSpan]:
    spans: list[HighlightSpan] = []
    for row in rows:
        for key in ("pred", "gold"):
            record = row.get(key)
            if not isinstance(record, dict):
                continue
            start, end = get_position(record)
            if end <= start:
                continue
            entity_type = str(record.get("type", ""))
            label = f"{source}:{key} {entity_type}"
            title = f"{row.get('category', row.get('match_kind', source))} | {record.get('text', '')} | {start}:{end}"
            spans.append(HighlightSpan(start=start, end=end, label=label, source=source, title=title))
    return spans


def render_highlighted_text(raw_text: str, spans: list[HighlightSpan]) -> str:
    """Return HTML with non-overlapping spans highlighted.

    Streamlit renders markdown HTML reliably if spans are simple inline tags. For overlapping
    spans, keep the higher-priority/earlier one and skip later overlaps so offsets remain clear.
    """
    valid_spans = _select_non_overlapping_spans(raw_text, spans)
    chunks: list[str] = []
    cursor = 0
    for span in valid_spans:
        chunks.append(html.escape(raw_text[cursor : span.start]))
        text = html.escape(raw_text[span.start : span.end])
        color = SOURCE_COLORS.get(span.source) or TYPE_COLORS.get(_extract_type(span.label), "#E5E7EB")
        border = _border_color(span.source)
        title = html.escape(span.title or span.label)
        label = html.escape(span.label)
        chunks.append(
            f'<mark title="{title}" style="background:{color}; border-bottom:2px solid {border}; padding:1px 2px; border-radius:3px;">'
            f'{text}<span style="font-size:0.70em; color:#374151; margin-left:3px;">{label}</span></mark>'
        )
        cursor = span.end
    chunks.append(html.escape(raw_text[cursor:]))
    return '<div style="white-space: pre-wrap; font-family: Consolas, Menlo, monospace; line-height: 1.65; font-size: 0.95rem;">' + "".join(chunks) + "</div>"


def _select_non_overlapping_spans(raw_text: str, spans: list[HighlightSpan]) -> list[HighlightSpan]:
    max_len = len(raw_text)
    priority = {
        "tp": 0,
        "span_mismatch": 1,
        "type_mismatch": 1,
        "assertion_mismatch": 1,
        "candidate_mismatch": 1,
        "fp": 2,
        "fn": 2,
        "gold": 3,
        "prediction": 4,
        "live": 4,
    }
    cleaned = [
        HighlightSpan(max(0, span.start), min(max_len, span.end), span.label, span.source, span.title)
        for span in spans
        if 0 <= span.start < span.end <= max_len
    ]
    cleaned.sort(key=lambda span: (span.start, priority.get(span.source, 9), -(span.end - span.start), span.end))
    selected: list[HighlightSpan] = []
    cursor = -1
    for span in cleaned:
        if span.start < cursor:
            continue
        selected.append(span)
        cursor = span.end
    return selected


def _extract_type(label: str) -> str:
    for entity_type in TYPE_COLORS:
        if entity_type in label:
            return entity_type
    return ""


def _border_color(source: str) -> str:
    return {
        "gold": "#16A34A",
        "prediction": "#2563EB",
        "tp": "#15803D",
        "fp": "#DC2626",
        "fn": "#EA580C",
        "span_mismatch": "#7C3AED",
        "type_mismatch": "#CA8A04",
        "assertion_mismatch": "#DB2777",
        "candidate_mismatch": "#0891B2",
        "live": "#4F46E5",
    }.get(source, "#6B7280")
