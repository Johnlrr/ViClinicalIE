from __future__ import annotations

from src.extractors.utils import dedupe_candidates, make_span_candidate


def test_make_span_candidate_uses_raw_slice() -> None:
    raw = "Bệnh nhân ho sốt"
    cand = make_span_candidate(raw, 10, 12, raw_type="TRIỆU_CHỨNG", source="test", score=1.0)

    assert cand.text == raw[10:12]
    assert cand.text == "ho"


def test_dedupe_candidates_keeps_highest_score() -> None:
    raw = "ho ho"
    low = make_span_candidate(raw, 0, 2, raw_type="TRIỆU_CHỨNG", source="test", score=0.1)
    high = make_span_candidate(raw, 0, 2, raw_type="TRIỆU_CHỨNG", source="test", score=0.9)

    assert dedupe_candidates([low, high]) == [high]
