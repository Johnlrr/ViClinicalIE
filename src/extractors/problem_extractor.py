from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.data_types import SpanCandidate
from src.extractors.base import BaseExtractor, ExtractionContext
from src.extractors.utils import dedupe_candidates, make_span_candidate, trim_trailing_punctuation


_STOP_WORDS = r"và|hoặc|nhưng|tuy\s+nhiên|song|được|đã|đang|không|chưa|cho|thấy|ghi\s+nhận|gợi\s+ý|lo\s+ngại"
_TAIL = rf"(?:\s+(?!(?:{_STOP_WORDS})\b)[\wÀ-ỹ%/.-]+){{0,8}}"

_SYMPTOM_PATTERNS = [
    rf"\bkhó\s+thở{_TAIL}",
    rf"\bđau{_TAIL}",
    rf"\b(?:ho|sốt|buồn\s+nôn|nôn|tiêu\s+chảy|táo\s+bón|chóng\s+mặt|mệt\s+mỏi|yếu|ngất|phù|sưng|chảy\s+máu|khó\s+nuốt|khò\s+khè|lo\s+âu|mất\s+ngủ|ảo\s+giác|lú\s+lẫn|nhìn\s+mờ){_TAIL}",
]
_DISEASE_PATTERNS = [
    rf"\brung\s+nhĩ{_TAIL}",
    rf"\bxơ\s+gan{_TAIL}",
    rf"\bphình\s+động\s+mạch{_TAIL}",
    rf"\b(?:viêm|ung\s+thư|u\s+ác|u\s+tuyến|suy|nhồi\s+máu|thuyên\s+tắc|xuất\s+huyết|hẹp|tắc|bóc\s+tách|gãy|áp\s+xe|nhiễm\s+khuẩn|nhiễm\s+trùng|bệnh|hội\s+chứng|loét|tràn\s+dịch){_TAIL}",
]


class ProblemExtractor(BaseExtractor):
    name = "problem_rule"

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.symptom_regexes = [re.compile(pattern, flags=re.IGNORECASE) for pattern in _SYMPTOM_PATTERNS]
        self.disease_regexes = [re.compile(pattern, flags=re.IGNORECASE) for pattern in _DISEASE_PATTERNS]

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        candidates: list[SpanCandidate] = []
        for chunk in context.chunks:
            for regex in self.symptom_regexes:
                candidates.extend(self._extract_with_regex(context, chunk, regex, "TRIỆU_CHỨNG", "symptom_head"))
            for regex in self.disease_regexes:
                candidates.extend(self._extract_with_regex(context, chunk, regex, "CHẨN_ĐOÁN", "disease_head"))
        return dedupe_candidates(candidates)

    def _extract_with_regex(self, context: ExtractionContext, chunk, regex: re.Pattern[str], raw_type: str, rule: str) -> list[SpanCandidate]:
        output: list[SpanCandidate] = []
        for match in regex.finditer(chunk.text):
            start = chunk.start + match.start()
            end = chunk.start + match.end()
            start, end = trim_trailing_punctuation(context.raw_text, start, end)
            if end <= start:
                continue
            output.append(
                make_span_candidate(
                    context.raw_text,
                    start,
                    end,
                    raw_type=raw_type,
                    source=self.name,
                    score=0.76,
                    chunk=chunk,
                    features={"rule": rule},
                )
            )
        return output
