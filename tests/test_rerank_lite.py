from __future__ import annotations

from src.data_types import MappingCandidate
from src.linking.drug_parser import parse_drug_mention
from src.linking.rerank_lite import rerank_icd_candidates, rerank_rxnorm_candidates


def C(code: str, score: float, alias: str, **metadata) -> MappingCandidate:
    return MappingCandidate(
        code=code,
        name=metadata.pop("name", alias),
        terminology=metadata.pop("terminology", "RXNORM"),
        lexical_score=score,
        final_score=score,
        metadata={"alias": alias, **metadata},
    )


def test_rxnorm_rerank_penalizes_unmentioned_combination_product() -> None:
    parsed = parse_drug_mention("aspirin 325mg x 1", {})
    candidates = [
        C(
            "combo",
            0.95,
            "aspirin 325 MG / carisoprodol 200 MG Oral Tablet",
            ingredient_guess="aspirin",
            strength_value=325.0,
            strength_unit="MG",
            tty="SCD",
            dose_form_guess="Oral Tablet",
        ),
        C(
            "plain",
            0.94,
            "aspirin 325 MG Oral Tablet",
            ingredient_guess="aspirin",
            strength_value=325.0,
            strength_unit="MG",
            tty="SCD",
            dose_form_guess="Oral Tablet",
        ),
    ]

    reranked = rerank_rxnorm_candidates(candidates, "aspirin 325mg x 1", parsed, config={"enabled": True})

    assert reranked[0].code == "plain"
    assert "unmentioned_combination_penalty" in reranked[1].metadata["rerank_lite"]["reasons"]


def test_rxnorm_rerank_penalizes_unmentioned_brand() -> None:
    parsed = parse_drug_mention("aspirin 325mg", {})
    candidates = [
        C(
            "brand",
            0.95,
            "aspirin 325 MG Oral Tablet [Bufferin]",
            ingredient_guess="aspirin",
            strength_value=325.0,
            strength_unit="MG",
            tty="SBD",
            dose_form_guess="Oral Tablet",
        ),
        C(
            "generic",
            0.94,
            "aspirin 325 MG Oral Tablet",
            ingredient_guess="aspirin",
            strength_value=325.0,
            strength_unit="MG",
            tty="SCD",
            dose_form_guess="Oral Tablet",
        ),
    ]

    reranked = rerank_rxnorm_candidates(candidates, "aspirin 325mg", parsed, config={"enabled": True})

    assert reranked[0].code == "generic"
    assert "unmentioned_brand_penalty" in reranked[1].metadata["rerank_lite"]["reasons"]


def test_icd_rerank_keeps_manual_override_at_top() -> None:
    candidates = [
        MappingCandidate(
            code="K72.9",
            name="Suy gan, không xác định",
            terminology="ICD10",
            lexical_score=0.90,
            final_score=0.90,
            metadata={"alias": "hội chứng não gan", "retriever": "manual_override"},
        ),
        MappingCandidate(
            code="K72",
            name="Suy gan",
            terminology="ICD10",
            lexical_score=0.91,
            final_score=0.91,
            metadata={"alias": "suy gan", "retriever": "bm25"},
        ),
    ]

    reranked = rerank_icd_candidates(candidates, "hội chứng não gan", config={"enabled": True})


    assert reranked[0].code == "K72.9"
    assert "manual_override_bonus" in reranked[0].metadata["rerank_lite"]["reasons"]
