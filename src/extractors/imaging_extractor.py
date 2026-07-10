from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.data_types import SpanCandidate
from src.extractors.base import BaseExtractor, ExtractionContext
from src.extractors.utils import dedupe_candidates, make_span_candidate, trim_trailing_punctuation


_IMAGING_RE = re.compile(
    r"""
    (?P<test>
      (?:chụp\s+)?(?:x\s*-?\s*quang|ct|mri)
      |cộng\s+hưởng\s+từ
      |siêu\s+âm
      |điện\s+tâm\s+đồ
      |ecg|ekg
      |monitor\s+holter
      |xạ\s+hình
    )
    (?P<tail>(?:\s+(?!(?:bình\s+thường|không|cho|thấy|ghi\s+nhận|âm\s+tính|dương\s+tính|gợi\s+ý)\b)[\wÀ-ỹ%/.-]+){0,6})
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


class ImagingExtractor(BaseExtractor):
    name = "imaging_rule"

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def extract(self, context: ExtractionContext) -> list[SpanCandidate]:
        candidates: list[SpanCandidate] = []
        for chunk in context.chunks:
            for match in _IMAGING_RE.finditer(chunk.text):
                start = chunk.start + match.start()
                end = chunk.start + match.end()
                start, end = trim_trailing_punctuation(context.raw_text, start, end)
                candidates.append(
                    make_span_candidate(
                        context.raw_text,
                        start,
                        end,
                        raw_type="TÊN_XÉT_NGHIỆM",
                        source=self.name,
                        score=0.78,
                        chunk=chunk,
                        features={"pattern": "imaging_test"},
                    )
                )
        return dedupe_candidates(candidates)
