from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.data_types import FinalEntity


ASSERTABLE_TYPES: set[str] = {"TRIỆU_CHỨNG", "CHẨN_ĐOÁN", "THUỐC"}
ASSERTION_ORDER: tuple[str, ...] = ("isNegated", "isHistorical", "isFamily")

DEFAULT_RULES: dict[str, list[str]] = {
    "negation_pre": [
        "không có",
        "không thấy",
        "không ghi nhận",
        "chưa ghi nhận",
        "chưa phát hiện",
        "phủ nhận",
        "loại trừ",
        "không",
    ],
    "negation_post": ["không ghi nhận bất thường", "không bất thường", "âm tính", "bình thường"],
    "pseudo_negation": ["không loại trừ", "không rõ", "không chắc", "chưa rõ"],
    "scope_terminators": ["nhưng", "tuy nhiên", "song", ".", ";", "\n"],
    "historical_cues": [
        "thuốc trước khi nhập viện",
        "trước khi nhập viện",
        "tiền sử",
        "trước đây",
        "đã từng",
        "mạn tính",
        "tại nhà",
        "đang dùng tại nhà",
        "đã ngừng",
        "ngừng uống",
        "cách nhập viện",
        "lần nhập viện trước",
    ],
    "current_event_overrides": [
        "lý do nhập viện",
        "hiện tại",
        "lúc vào viện",
        "khi nhập viện",
        "được chỉ định",
        "được cho dùng",
        "được cho",
        "bắt đầu",
        "điều trị tại bệnh viện",
        "phát hiện mới",
        "tại cấp cứu",
    ],
    "family_members": [
        "nhiều thành viên trong gia đình",
        "thành viên trong gia đình",
        "người nhà",
        "gia đình",
        "bố",
        "mẹ",
        "cha",
        "anh",
        "chị",
        "em",
        "con",
        "vợ",
        "chồng",
    ],
    "family_experiencer_verbs": ["mắc", "có", "bị", "bệnh", "triệu chứng", "tương tự"],
    "reporter_verbs": ["phát hiện", "nhận thấy", "đưa", "kể", "báo", "cho biết", "gọi", "cung cấp"],
}

DEFAULT_ASSERTION_CONFIG: dict[str, Any] = {
    "assertable_types": sorted(ASSERTABLE_TYPES),
    "window_chars_left": 160,
    "window_chars_right": 160,
    "thresholds": {
        "isNegated": 0.55,
        "isHistorical": 0.60,
        "isFamily": 0.80,
    },
    "section_priors": {
        "PAST_HISTORY": {"isHistorical": 0.25},
        "PAST_MEDICAL_HISTORY": {"isHistorical": 0.30},
        "PRE_ADMISSION_MEDICATION": {"isHistorical": 0.35},
    },
}


@dataclass(slots=True)
class ContextWindow:
    raw_text: str
    start: int
    end: int
    text: str
    entity: FinalEntity

    @property
    def left_text(self) -> str:
        return self.raw_text[self.start : self.entity.start]

    @property
    def right_text(self) -> str:
        return self.raw_text[self.entity.end : self.end]


@dataclass(slots=True)
class CueMatch:
    cue: str
    start: int
    end: int


@dataclass(slots=True)
class AssertionEvidence:
    assertion: str
    score: float
    cue: str
    cue_start: int | None
    cue_end: int | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion": self.assertion,
            "score": self.score,
            "cue": self.cue,
            "cue_start": self.cue_start,
            "cue_end": self.cue_end,
            "reason": self.reason,
        }


@dataclass(slots=True)
class AssertionDecision:
    assertions: list[str]
    scores: dict[str, float]
    evidence: list[AssertionEvidence]


def load_assertion_rules(path: str | Path) -> dict[str, list[str]]:
    rules_path = Path(path)
    with rules_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Assertion rules YAML must contain a mapping: {rules_path}")
    return {str(key): _string_list(value) for key, value in data.items()}


def build_assertion_config(config: Mapping[str, Any] | None = None, rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = {
        **DEFAULT_ASSERTION_CONFIG,
        "thresholds": dict(DEFAULT_ASSERTION_CONFIG["thresholds"]),
        "section_priors": dict(DEFAULT_ASSERTION_CONFIG["section_priors"]),
        "rules": {key: list(value) for key, value in DEFAULT_RULES.items()},
    }
    incoming = dict(config or {})
    merged.update({key: value for key, value in incoming.items() if key not in {"thresholds", "section_priors", "rules"}})
    if isinstance(incoming.get("thresholds"), Mapping):
        merged["thresholds"].update(dict(incoming["thresholds"]))
    if isinstance(incoming.get("section_priors"), Mapping):
        section_priors = dict(merged["section_priors"])
        for section, priors in dict(incoming["section_priors"]).items():
            section_priors[str(section)] = dict(priors) if isinstance(priors, Mapping) else priors
        merged["section_priors"] = section_priors

    configured_rules: dict[str, list[str]] = {key: list(value) for key, value in DEFAULT_RULES.items()}
    for source in (incoming.get("rules"), incoming, rules):
        if not isinstance(source, Mapping):
            continue
        for key in DEFAULT_RULES:
            if key in source:
                configured_rules[key] = _string_list(source[key])
    merged["rules"] = configured_rules
    return merged


def get_context_window(raw_text: str, entity: FinalEntity, left: int = 160, right: int = 160) -> ContextWindow:
    start = max(0, entity.start - left)
    end = min(len(raw_text), entity.end + right)
    return ContextWindow(raw_text=raw_text, start=start, end=end, text=raw_text[start:end], entity=entity)


def find_cues(raw_text: str, cues: list[str] | tuple[str, ...], start: int = 0, end: int | None = None) -> list[CueMatch]:
    search_end = len(raw_text) if end is None else end
    segment = raw_text[start:search_end]
    matches: list[CueMatch] = []
    for cue in sorted({cue.strip() for cue in cues if str(cue).strip()}, key=len, reverse=True):
        pattern = _cue_pattern(cue)
        for match in re.finditer(pattern, segment, flags=re.IGNORECASE | re.UNICODE):
            matches.append(CueMatch(cue=cue, start=start + match.start(), end=start + match.end()))
    return sorted(matches, key=lambda item: (item.start, -(item.end - item.start)))


def contains_cue(raw_text: str, cues: list[str] | tuple[str, ...], start: int = 0, end: int | None = None) -> bool:
    return bool(find_cues(raw_text, cues, start, end))


def has_terminator_between(raw_text: str, start: int, end: int, terminators: list[str] | tuple[str, ...]) -> bool:
    if start >= end:
        return False
    segment = raw_text[start:end]
    for terminator in terminators:
        if not terminator:
            continue
        if terminator in {".", ";", "\n", "\r", "\r\n"}:
            if terminator in segment:
                return True
            continue
        if find_cues(segment, [terminator]):
            return True
    return False


def section_of(entity: FinalEntity) -> str | None:
    section = entity.provenance.get("section") if isinstance(entity.provenance, dict) else None
    return str(section) if section else None


def evidence_to_provenance(evidence: list[AssertionEvidence]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in evidence]


def _cue_pattern(cue: str) -> str:
    escaped = re.escape(cue)
    prefix = r"(?<!\w)" if cue[0].isalnum() else ""
    suffix = r"(?!\w)" if cue[-1].isalnum() else ""
    return f"{prefix}{escaped}{suffix}"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]