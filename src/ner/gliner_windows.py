from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from src.data_types import Chunk


_TOKEN_RE = re.compile(r"\S+", flags=re.UNICODE)


class TokenCounter(Protocol):
    def token_offsets(self, text: str) -> list[tuple[int, int]]: ...


class RegexTokenCounter:
    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in _TOKEN_RE.finditer(text)]


class TransformersTokenCounter:
    def __init__(self, tokenizer_name_or_path: str, *, revision: str | None = None, local_files_only: bool = False) -> None:
        from transformers import AutoTokenizer  # type: ignore

        self.tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_name_or_path,
            use_fast=True,
            revision=revision,
            local_files_only=local_files_only,
        )

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        encoded = self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return [(int(start), int(end)) for start, end in encoded["offset_mapping"] if int(end) > int(start)]


@dataclass(frozen=True, slots=True)
class GLiNERWindow:
    window_id: str
    parent_chunk_id: int
    text: str
    start: int
    end: int
    token_count: int
    section: str | None = None
    subsection: str | None = None


def build_gliner_windows(
    raw_text: str,
    chunks: Sequence[Chunk],
    *,
    max_tokens: int = 320,
    overlap_tokens: int = 64,
    counter: TokenCounter | None = None,
) -> list[GLiNERWindow]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must satisfy 0 <= overlap_tokens < max_tokens")
    tokenizer = counter or RegexTokenCounter()
    parents = list(chunks) or [Chunk(raw_text, 0, len(raw_text))]
    windows: list[GLiNERWindow] = []
    for parent_id, chunk in enumerate(parents):
        if raw_text[chunk.start:chunk.end] != chunk.text:
            raise ValueError(f"Chunk offset mismatch for parent {parent_id}")
        offsets = tokenizer.token_offsets(chunk.text)
        if not offsets:
            continue
        step = max_tokens - overlap_tokens
        token_start = 0
        window_index = 0
        while token_start < len(offsets):
            token_end = min(len(offsets), token_start + max_tokens)
            local_start = offsets[token_start][0]
            local_end = offsets[token_end - 1][1]
            start = chunk.start + local_start
            end = chunk.start + local_end
            window_text = raw_text[start:end]
            windows.append(
                GLiNERWindow(
                    window_id=f"c{parent_id}:w{window_index}",
                    parent_chunk_id=parent_id,
                    text=window_text,
                    start=start,
                    end=end,
                    token_count=token_end - token_start,
                    section=chunk.section,
                    subsection=chunk.subsection,
                )
            )
            if token_end == len(offsets):
                break
            token_start += step
            window_index += 1
    return windows