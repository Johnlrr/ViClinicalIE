from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Iterable, Mapping

from src.data_types import MappingCandidate
from src.linking.drug_parser import ParsedDrug
from src.linking.terminology_normalizer import normalize_for_lookup, tokenize_for_lookup


_COMBINATION_MARKERS = ("/", " and ", " with ", " + ")
_BRACKETED_BRAND_RE = re.compile(r"\[[^\]]+\]")
_COMMON_ROUTE_FORM_HINTS = {
    "po": "oral",
    "uống": "oral",
    "uong": "oral",
    "oral": "oral",
    "iv": "injection",
    "tm": "injection",
    "tiêm": "injection",
    "tiem": "injection",
    "truyền": "injection",
    "truyen": "injection",
    "nebulizer": "inhalation",
    "neb": "inhalation",
}


def rerank_icd_candidates(
    candidates: Iterable[MappingCandidate],
    mention: str,
    context: str = "",
    config: Mapping[str, Any] | None = None,
) -> list[MappingCandidate]:
    """Apply deterministic, conservative reranking to ICD candidates.

    This function does not create candidates. It only adjusts score/order using
    transparent lexical signals that are already present in the candidate
    metadata. The output is sorted by adjusted score descending.
    """

    cfg = _cfg(config)
    if not bool(cfg.get("enabled", True)):
        return list(candidates)

    adjusted: list[MappingCandidate] = []
    mention_norm = normalize_for_lookup(mention)
    context_norm = normalize_for_lookup(context)
    for candidate in candidates:
        metadata = dict(candidate.metadata)
        score = float(candidate.final_score)
        alias = str(metadata.get("alias") or candidate.name or "")
        alias_norm = normalize_for_lookup(alias)
        retriever = str(metadata.get("retriever") or metadata.get("match_type") or "")
        alias_source = str(metadata.get("alias_source") or "")

        bonus = 0.0
        penalty = 0.0
        reasons: list[str] = []

        if retriever == "manual_override":
            bonus += float(cfg.get("icd_manual_override_bonus", 0.03))
            reasons.append("manual_override_bonus")
        if retriever == "exact_alias":
            bonus += float(cfg.get("icd_exact_alias_bonus", 0.02))
            reasons.append("exact_alias_bonus")
        if alias_source == "manual":
            bonus += float(cfg.get("icd_manual_alias_bonus", 0.01))
            reasons.append("manual_alias_bonus")

        closeness = _token_f1(mention_norm, alias_norm)
        if closeness >= 0.95:
            bonus += float(cfg.get("icd_close_alias_bonus", 0.02))
            reasons.append("close_alias_bonus")
        elif closeness < float(cfg.get("icd_weak_alias_threshold", 0.45)):
            penalty += float(cfg.get("icd_weak_alias_penalty", 0.05))
            reasons.append("weak_alias_penalty")

        if _is_broad_icd_code(candidate.code) and len(tokenize_for_lookup(mention)) >= 3:
            penalty += float(cfg.get("icd_broad_code_penalty", 0.015))
            reasons.append("broad_code_penalty")

        if context_norm and any(marker in context_norm for marker in ("chẩn đoán", "chan doan", "bệnh", "benh", "viêm", "viem")):
            bonus += float(cfg.get("icd_context_bonus", 0.005))
            reasons.append("diagnosis_context_bonus")

        final_score = _clip(score + bonus - penalty)
        metadata["rerank_lite"] = {
            "enabled": True,
            "base_score": round(score, 6),
            "bonus": round(bonus, 6),
            "penalty": round(penalty, 6),
            "alias_token_f1": round(closeness, 6),
            "reasons": reasons,
        }
        adjusted.append(replace(candidate, rerank_score=score + bonus - penalty, final_score=final_score, metadata=metadata))
    return sorted(adjusted, key=_rank_key, reverse=True)


def rerank_rxnorm_candidates(
    candidates: Iterable[MappingCandidate],
    mention: str,
    parsed: ParsedDrug,
    context: str = "",
    config: Mapping[str, Any] | None = None,
) -> list[MappingCandidate]:
    """Apply deterministic reranking to RxNorm candidates.

    Main safety goals:
    - prefer exact ingredient + strength matches;
    - prefer simple single-ingredient clinical drugs over combination products
      unless the mention explicitly contains multiple ingredients;
    - prefer generic/non-brand rows unless a brand is explicitly matched;
    - do not hallucinate codes outside the retrieved pool.
    """

    cfg = _cfg(config)
    if not bool(cfg.get("enabled", True)):
        return list(candidates)

    adjusted: list[MappingCandidate] = []
    mention_norm = normalize_for_lookup(mention)
    context_norm = normalize_for_lookup(context)
    mention_tokens = set(tokenize_for_lookup(mention_norm))
    parsed_name = normalize_for_lookup(parsed.normalized_name)
    mention_has_combo_marker = any(marker.strip() and marker in mention_norm for marker in ("/", "+", " and ", " và ", " va "))
    route_hint = _route_hint(mention_norm, context_norm)

    for candidate in candidates:
        metadata = dict(candidate.metadata)
        score = float(candidate.final_score)
        alias = str(metadata.get("alias") or candidate.name or "")
        alias_norm = normalize_for_lookup(alias)
        candidate_name_norm = normalize_for_lookup(candidate.name)
        ingredient = normalize_for_lookup(metadata.get("ingredient_guess", ""))
        tty = str(metadata.get("tty") or "")
        alias_source = str(metadata.get("alias_source") or "")
        match_type = str(metadata.get("match_type") or metadata.get("retriever") or "")
        dose_form = normalize_for_lookup(metadata.get("dose_form_guess", ""))
        row_strength_value = _float_or_none(metadata.get("strength_value"))
        row_strength_unit = normalize_for_lookup(metadata.get("strength_unit", ""))

        bonus = 0.0
        penalty = 0.0
        reasons: list[str] = []

        if match_type == "manual_override" or str(metadata.get("retriever") or "") == "manual_override":
            bonus += float(cfg.get("rx_manual_override_bonus", 0.30))
            reasons.append("manual_override_bonus")

        is_manual_override = match_type == "manual_override" or str(metadata.get("retriever") or "") == "manual_override"
        if parsed_name and ingredient == parsed_name:
            bonus += float(cfg.get("rx_ingredient_match_bonus", 0.04))
            reasons.append("ingredient_match_bonus")
        elif parsed_name and ingredient and ingredient != parsed_name and not is_manual_override:
            penalty += float(cfg.get("rx_ingredient_mismatch_penalty", 0.18))
            reasons.append("ingredient_mismatch_penalty")

        if parsed.strength_value is not None:
            if row_strength_value is not None and abs(row_strength_value - parsed.strength_value) < 1e-6:
                bonus += float(cfg.get("rx_strength_match_bonus", 0.04))
                reasons.append("strength_match_bonus")
                if parsed.strength_unit and row_strength_unit == normalize_for_lookup(parsed.strength_unit):
                    bonus += float(cfg.get("rx_unit_match_bonus", 0.02))
                    reasons.append("unit_match_bonus")
            elif row_strength_value is not None and not is_manual_override:
                penalty += float(cfg.get("rx_strength_mismatch_penalty", 0.25))
                reasons.append("strength_mismatch_penalty")

        if _looks_like_combination(alias_norm, candidate_name_norm) and not mention_has_combo_marker and not is_manual_override:
            penalty += float(cfg.get("rx_unmentioned_combination_penalty", 0.18))
            reasons.append("unmentioned_combination_penalty")

        if _has_bracketed_brand(alias) and not _brand_mentioned(alias, mention_norm) and not is_manual_override:
            penalty += float(cfg.get("rx_unmentioned_brand_penalty", 0.05))
            reasons.append("unmentioned_brand_penalty")

        if tty in {"SCD", "SCDC", "SCDF"}:
            bonus += float(cfg.get("rx_generic_clinical_bonus", 0.015))
            reasons.append("generic_clinical_bonus")
        elif tty in {"SBD", "SBDC", "SBDF"} and not _brand_mentioned(alias, mention_norm) and not is_manual_override:
            penalty += float(cfg.get("rx_unmentioned_sbd_penalty", 0.04))
            reasons.append("unmentioned_sbd_penalty")

        if route_hint and dose_form:
            if route_hint == "oral" and any(token in dose_form for token in ("oral", "tablet", "capsule")):
                bonus += float(cfg.get("rx_route_form_match_bonus", 0.01))
                reasons.append("route_form_match_bonus")
            elif route_hint == "injection" and any(token in dose_form for token in ("injection", "injectable", "solution")):
                bonus += float(cfg.get("rx_route_form_match_bonus", 0.01))
                reasons.append("route_form_match_bonus")
            elif route_hint == "inhalation" and any(token in dose_form for token in ("inhal", "nebul")):
                bonus += float(cfg.get("rx_route_form_match_bonus", 0.01))
                reasons.append("route_form_match_bonus")

        # Prefer full RxNorm STR / ingredient-strength evidence over generic
        # ingredient rows when strength is explicitly present in the mention.
        if parsed.strength_value is not None and match_type in {"ingredient_strength", "rxnorm_str", "tfidf", "bm25"}:
            bonus += float(cfg.get("rx_strength_evidence_source_bonus", 0.01))
            reasons.append("strength_evidence_source_bonus")
        if alias_source == "ingredient_guess" and parsed.strength_value is not None and len(mention_tokens) >= 2:
            penalty += float(cfg.get("rx_bare_ingredient_alias_penalty", 0.03))
            reasons.append("bare_ingredient_alias_penalty")

        alias_closeness = _token_f1(mention_norm, alias_norm)
        if alias_closeness >= 0.75:
            bonus += float(cfg.get("rx_alias_closeness_bonus", 0.01))
            reasons.append("alias_closeness_bonus")

        final_score = _clip(score + bonus - penalty)
        metadata["rerank_lite"] = {
            "enabled": True,
            "base_score": round(score, 6),
            "bonus": round(bonus, 6),
            "penalty": round(penalty, 6),
            "alias_token_f1": round(alias_closeness, 6),
            "route_hint": route_hint,
            "reasons": reasons,
        }
        adjusted.append(replace(candidate, rerank_score=score + bonus - penalty, final_score=final_score, metadata=metadata))
    return sorted(adjusted, key=_rank_key, reverse=True)


def _cfg(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(config, Mapping):
        return {"enabled": True}
    return config


def _rank_key(candidate: MappingCandidate) -> tuple[float, float, str]:
    return (float(candidate.rerank_score or candidate.final_score), float(candidate.final_score), str(candidate.code))


def _clip(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _token_f1(left: str, right: str) -> float:
    left_tokens = set(tokenize_for_lookup(left))
    right_tokens = set(tokenize_for_lookup(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    precision = len(overlap) / len(right_tokens)
    recall = len(overlap) / len(left_tokens)
    return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


def _is_broad_icd_code(code: str) -> bool:
    value = str(code).strip().upper()
    return bool(value) and "." not in value and len(value) <= 3


def _looks_like_combination(alias_norm: str, candidate_name_norm: str) -> bool:
    text = f" {alias_norm} {candidate_name_norm} "
    return any(marker in text for marker in _COMBINATION_MARKERS)


def _has_bracketed_brand(alias: str) -> bool:
    return bool(_BRACKETED_BRAND_RE.search(alias))


def _brand_mentioned(alias: str, mention_norm: str) -> bool:
    for match in _BRACKETED_BRAND_RE.findall(alias):
        brand = normalize_for_lookup(match.strip("[]"))
        if brand and brand in mention_norm:
            return True
    return False


def _route_hint(mention_norm: str, context_norm: str) -> str:
    window = f" {mention_norm} {context_norm} "
    for cue, hint in _COMMON_ROUTE_FORM_HINTS.items():
        if f" {cue} " in window or cue in mention_norm:
            return hint
    return ""
