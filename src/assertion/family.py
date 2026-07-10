from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.data_types import FinalEntity
from src.assertion.context_rules import AssertionEvidence, contains_cue, find_cues, get_context_window, has_terminator_between


def detect_family(entity: FinalEntity, raw_text: str, config: Mapping[str, Any]) -> AssertionEvidence | None:
    rules = dict(config.get("rules", {}))
    left = int(config.get("window_chars_left", 160))
    right = int(config.get("window_chars_right", 160))
    window = get_context_window(raw_text, entity, left=left, right=right)
    terminators = rules.get("scope_terminators", [])
    family_matches = find_cues(raw_text, rules.get("family_members", []), window.start, entity.start)
    for match in sorted(family_matches, key=lambda item: item.end, reverse=True):
        if has_terminator_between(raw_text, match.end, entity.start, terminators):
            continue
        between_start = match.end
        between_end = entity.start
        if contains_cue(raw_text, rules.get("reporter_verbs", []), between_start, between_end):
            continue
        if contains_cue(raw_text, ["bệnh nhân", "bn"], between_start, between_end):
            continue
        if not contains_cue(raw_text, rules.get("family_experiencer_verbs", []), between_start, min(len(raw_text), entity.end + 40)):
            continue
        return AssertionEvidence(
            assertion="isFamily",
            score=0.90,
            cue=match.cue,
            cue_start=match.start,
            cue_end=match.end,
            reason="family_member_experiencer_scope",
        )
    return None