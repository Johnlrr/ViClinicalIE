from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.data_types import Chunk, PreprocessOutput
from src.preprocess.normalizer import build_text_views


DEFAULT_CHUNK_CONFIG: dict[str, Any] = {
    "split_on_newlines": True,
    "split_on_sentence_punctuation": True,
    "max_chunk_chars": 500,
    "min_split_fraction": 0.4,
    "bullet_patterns": [r"^\s*[-*•]\s+", r"^\s*\d+[.)]\s+", r"^\s*[a-zA-Z][.)]\s+"],
}

_LINE_END_RE = re.compile(r"\r\n|\n|\r")
_PUNCT_SPLIT_RE = re.compile(r"[.!?;:。！？؛]")


def preprocess_text(raw_text: str, config: Mapping[str, Any] | None = None) -> PreprocessOutput:
    cfg = dict(config or {})
    views = build_text_views(raw_text, cfg.get("preprocess", cfg))
    chunks = chunk_text(raw_text, cfg.get("chunking", cfg))
    return PreprocessOutput(raw_text=raw_text, views=views, chunks=chunks)


def chunk_text(raw_text: str, config: Mapping[str, Any] | None = None) -> list[Chunk]:
    cfg = {**DEFAULT_CHUNK_CONFIG, **dict(config or {})}
    max_chunk_chars = int(cfg.get("max_chunk_chars", 500))
    bullet_patterns = [re.compile(pattern) for pattern in cfg.get("bullet_patterns", [])]
    chunks: list[Chunk] = []

    for line_id, (line_start, line_end) in enumerate(_iter_line_content_spans(raw_text)):
        trimmed = _trim_span(raw_text, line_start, line_end)
        if trimmed is None:
            continue
        start, end = trimmed
        bullet_level = _detect_bullet_level(raw_text[start:end], bullet_patterns)
        for chunk_start, chunk_end in _split_span(raw_text, start, end, max_chunk_chars, cfg):
            text = raw_text[chunk_start:chunk_end]
            if not text:
                continue
            chunks.append(
                Chunk(
                    text=text,
                    start=chunk_start,
                    end=chunk_end,
                    section=None,
                    subsection=None,
                    line_id=line_id,
                    bullet_level=bullet_level,
                )
            )

    return chunks


def _iter_line_content_spans(raw_text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _LINE_END_RE.finditer(raw_text):
        spans.append((cursor, match.start()))
        cursor = match.end()
    if cursor <= len(raw_text):
        spans.append((cursor, len(raw_text)))
    return spans


def _trim_span(raw_text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and raw_text[start].isspace():
        start += 1
    while end > start and raw_text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return start, end


def _detect_bullet_level(text: str, bullet_patterns: list[re.Pattern[str]]) -> int | None:
    for level, pattern in enumerate(bullet_patterns, start=1):
        if pattern.match(text):
            return level
    return None


def _split_span(
    raw_text: str,
    start: int,
    end: int,
    max_chunk_chars: int,
    cfg: Mapping[str, Any],
) -> list[tuple[int, int]]:
    if max_chunk_chars <= 0 or end - start <= max_chunk_chars:
        return [(start, end)]

    output: list[tuple[int, int]] = []
    cursor = start
    min_fraction = float(cfg.get("min_split_fraction", 0.4))
    while end - cursor > max_chunk_chars:
        limit = min(end, cursor + max_chunk_chars)
        min_split = cursor + max(1, int(max_chunk_chars * min_fraction))
        split_at = _find_split_point(raw_text, cursor, limit, min_split, cfg)
        if split_at <= cursor:
            split_at = limit
        trimmed = _trim_span(raw_text, cursor, split_at)
        if trimmed is not None:
            output.append(trimmed)
        cursor = split_at
        while cursor < end and raw_text[cursor].isspace():
            cursor += 1

    trimmed = _trim_span(raw_text, cursor, end)
    if trimmed is not None:
        output.append(trimmed)
    return output


def _find_split_point(
    raw_text: str,
    start: int,
    limit: int,
    min_split: int,
    cfg: Mapping[str, Any],
) -> int:
    if bool(cfg.get("split_on_sentence_punctuation", True)):
        candidate = -1
        for match in _PUNCT_SPLIT_RE.finditer(raw_text, start, limit):
            if match.end() >= min_split:
                candidate = match.end()
        if candidate != -1:
            return candidate

    for idx in range(limit - 1, min_split - 1, -1):
        if raw_text[idx].isspace():
            return idx + 1
    return limit
