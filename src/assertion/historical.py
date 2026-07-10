from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.data_types import FinalEntity
from src.assertion.context_rules import AssertionEvidence, contains_cue, find_cues, get_context_window, has_terminator_between, section_of


def detect_historical(entity: FinalEntity, raw_text: str, config: Mapping[str, Any]) -> AssertionEvidence | None:
    rules = dict(config.get("rules", {}))
    left = int(config.get("window_chars_left", 160))
    right = int(config.get("window_chars_right", 160))
    window = get_context_window(raw_text, entity, left=left, right=right)
    terminators = rules.get("scope_terminators", [])
    current_overrides = rules.get("current_event_overrides", [])

    historical_matches = find_cues(raw_text, rules.get("historical_cues", []), window.start, window.end)
    if _has_current_override_near_entity(entity, raw_text, current_overrides, historical_matches):
        return None
    before = [match for match in historical_matches if match.end <= entity.start]
    after = [match for match in historical_matches if match.start >= entity.end]
    for match in sorted(before, key=lambda item: entity.start - item.end):
        if not _cue_applies_to_entity(match.cue, entity):
            continue
        if has_terminator_between(raw_text, match.end, entity.start, terminators):
            continue
        return AssertionEvidence(
            assertion="isHistorical",
            score=_historical_score(match.cue, entity),
            cue=match.cue,
            cue_start=match.start,
            cue_end=match.end,
            reason="historical_cue_before_entity",
        )
    for match in sorted(after, key=lambda item: item.start - entity.end):
        if not _cue_applies_to_entity(match.cue, entity):
            continue
        if has_terminator_between(raw_text, entity.end, match.start, terminators):
            continue
        return AssertionEvidence(
            assertion="isHistorical",
            score=0.70,
            cue=match.cue,
            cue_start=match.start,
            cue_end=match.end,
            reason="historical_cue_after_entity",
        )

    section = section_of(entity)
    if str(entity.type) == "THUỐC" and section == "PRE_ADMISSION_MEDICATION":
        return AssertionEvidence(
            assertion="isHistorical",
            score=0.85,
            cue=section,
            cue_start=None,
            cue_end=None,
            reason="pre_admission_medication_section_drug_prior",
        )

    section_prior = _section_prior(entity, config)
    if section_prior >= float(config.get("thresholds", {}).get("isHistorical", 0.60)):
        return AssertionEvidence(
            assertion="isHistorical",
            score=section_prior,
            cue=section or "section_prior",
            cue_start=None,
            cue_end=None,
            reason="section_prior_without_current_override",
        )
    return None


def _has_current_override_near_entity(entity: FinalEntity, raw_text: str, current_overrides: list[str], historical_matches) -> bool:
    start = max(0, entity.start - 100)
    end = min(len(raw_text), entity.end + 60)
    for match in find_cues(raw_text, current_overrides, start, end):
        if any(_overlaps(match.start, match.end, historical.start, historical.end) for historical in historical_matches):
            continue
        return True
    return False


def _overlaps(first_start: int, first_end: int, second_start: int, second_end: int) -> bool:
    return max(first_start, second_start) < min(first_end, second_end)


def _cue_applies_to_entity(cue: str, entity: FinalEntity) -> bool:
    if str(entity.type) == "THUỐC":
        return True
    cue_norm = cue.casefold()
    drug_or_admission_specific_parts = (
        "thuốc",
        "đang dùng",
        "ngừng uống",
        "tại nhà",
        "trước khi nhập viện",
        "cách nhập viện",
    )
    return not any(part in cue_norm for part in drug_or_admission_specific_parts)


def _historical_score(cue: str, entity: FinalEntity) -> float:
    cue_norm = cue.casefold()
    if str(entity.type) == "THUỐC" and ("trước khi nhập viện" in cue_norm or "tại nhà" in cue_norm):
        return 0.90
    if "tiền sử" in cue_norm or "đã từng" in cue_norm or "trước đây" in cue_norm:
        return 0.88
    if "ngừng" in cue_norm or "cách nhập viện" in cue_norm:
        return 0.84
    return 0.75


def _section_prior(entity: FinalEntity, config: Mapping[str, Any]) -> float:
    section = section_of(entity)
    if not section:
        return 0.0
    priors = config.get("section_priors", {})
    if not isinstance(priors, Mapping):
        return 0.0
    section_scores = priors.get(section, {})
    if not isinstance(section_scores, Mapping):
        return 0.0
    return float(section_scores.get("isHistorical", 0.0))