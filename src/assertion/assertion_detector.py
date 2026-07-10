from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.assertion.context_rules import (
    ASSERTABLE_TYPES,
    ASSERTION_ORDER,
    AssertionDecision,
    AssertionEvidence,
    build_assertion_config,
    evidence_to_provenance,
)
from src.assertion.family import detect_family
from src.assertion.historical import detect_historical
from src.assertion.negation import detect_negation
from src.data_types import FinalEntity


class AssertionDetector:
    def __init__(self, config: Mapping[str, Any] | None = None, rules: Mapping[str, Any] | None = None) -> None:
        self.config = build_assertion_config(config, rules)
        self.assertable_types = set(self.config.get("assertable_types", ASSERTABLE_TYPES))
        self.thresholds = dict(self.config.get("thresholds", {}))

    def apply(self, entities: list[FinalEntity], raw_text: str) -> list[FinalEntity]:
        return [self.apply_one(entity, raw_text) for entity in entities]

    def apply_one(self, entity: FinalEntity, raw_text: str) -> FinalEntity:
        self._validate_entity_offsets(entity, raw_text)
        if str(entity.type) not in self.assertable_types:
            return self._copy_entity(entity, assertions=[], assertion_decision=None)

        evidence = [
            item
            for item in (
                detect_negation(entity, raw_text, self.config),
                detect_historical(entity, raw_text, self.config),
                detect_family(entity, raw_text, self.config),
            )
            if item is not None
        ]
        scores = {assertion: 0.0 for assertion in ASSERTION_ORDER}
        for item in evidence:
            scores[item.assertion] = max(scores.get(item.assertion, 0.0), item.score)
        assertions = [
            assertion
            for assertion in ASSERTION_ORDER
            if scores.get(assertion, 0.0) >= float(self.thresholds.get(assertion, 1.0))
        ]
        decision = AssertionDecision(assertions=assertions, scores=scores, evidence=evidence)
        return self._copy_entity(entity, assertions=assertions, assertion_decision=decision)

    def _copy_entity(
        self,
        entity: FinalEntity,
        assertions: list[str],
        assertion_decision: AssertionDecision | None,
    ) -> FinalEntity:
        provenance = dict(entity.provenance)
        if assertion_decision is not None:
            provenance["assertion"] = {
                "scores": assertion_decision.scores,
                "evidence": evidence_to_provenance(assertion_decision.evidence),
            }
        return FinalEntity(
            text=entity.text,
            start=entity.start,
            end=entity.end,
            type=entity.type,
            assertions=list(assertions),
            candidates=list(entity.candidates),
            confidence=entity.confidence,
            provenance=provenance,
        )

    def _validate_entity_offsets(self, entity: FinalEntity, raw_text: str) -> None:
        if raw_text[entity.start : entity.end] != entity.text:
            raise ValueError(f"Entity offset mismatch: {entity}")