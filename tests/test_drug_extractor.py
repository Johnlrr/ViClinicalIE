from __future__ import annotations

from src.extractors.base import ExtractionContext
from src.extractors.drug_extractor import DrugExtractor
from src.preprocess.chunker import preprocess_text


ALIASES = [
    {"alias": "metoprolol", "rxcui": "6918", "tty": "IN", "alias_source": "test"},
    {"alias": "aspirin", "rxcui": "1191", "tty": "IN", "alias_source": "test"},
    {"alias": "atenolol", "rxcui": "1202", "tty": "IN", "alias_source": "test"},
]


def test_drug_extractor_expands_dose_route_frequency() -> None:
    raw = "Thuốc trước khi nhập viện: metoprolol 25mg po bid, aspirin 325mg x 1."
    output = preprocess_text(raw)
    extractor = DrugExtractor(alias_rows=ALIASES)

    candidates = extractor.extract(ExtractionContext(raw, output.views, output.chunks))
    texts = {cand.text for cand in candidates}

    assert "metoprolol 25mg po bid" in texts
    assert "aspirin 325mg x 1" in texts
    for cand in candidates:
        assert raw[cand.start : cand.end] == cand.text


def test_drug_extractor_catches_plain_drug_name() -> None:
    raw = "Ở nhà bệnh nhân đã sử dụng atenolol."
    output = preprocess_text(raw)
    extractor = DrugExtractor(alias_rows=ALIASES)

    candidates = extractor.extract(ExtractionContext(raw, output.views, output.chunks))

    assert any(cand.text == "atenolol" for cand in candidates)
