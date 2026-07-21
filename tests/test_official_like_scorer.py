from __future__ import annotations

from src.evaluation.official_like_scorer import score_corpus, word_error_rate


def _record(text: str, start: int, entity_type: str, **extra):
    return {"text": text, "position": [start, start + len(text)], "type": entity_type, "assertions": [], **extra}


def test_gold_against_itself_is_perfect() -> None:
    gold = {"1": [_record("sốt", 0, "TRIỆU_CHỨNG"), _record("aspirin", 4, "THUỐC", candidates=["1191"])]}
    score = score_corpus(gold, gold)
    assert score.text_score == 1.0
    assert score.assertions_score == 1.0
    assert score.candidates_score == 1.0
    assert score.final_score == 1.0


def test_wrong_type_does_not_share_attribute_identity() -> None:
    gold = {"1": [_record("sốt", 0, "TRIỆU_CHỨNG", assertions=["isNegated"])]}
    pred = {"1": [_record("sốt", 0, "CHẨN_ĐOÁN", assertions=["isNegated"], candidates=[])]}
    score = score_corpus(pred, gold)
    assert score.assertions_score == 0.0


def test_word_error_rate_uses_word_level_edit_distance() -> None:
    assert word_error_rate("đau ngực", "đau bụng") == 0.5
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "sốt") == 1.0