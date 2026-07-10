from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from src.data_types import TextViews
from src.linking.terminology_normalizer import remove_vietnamese_diacritics


DEFAULT_PREPROCESS_CONFIG: dict[str, Any] = {
    "unicode_form": "NFC",
    "lowercase_normalized": True,
    "collapse_whitespace": True,
    "build_no_diacritics_view": True,
    "preserve_raw": True,
}


def build_text_views(raw_text: str, config: Mapping[str, Any] | None = None) -> TextViews:
    """Build normalized/search views while preserving char maps to raw text.

    The raw text is never mutated. Normalized/search/no-diacritics views are
    designed for matching and every emitted character maps to one raw character
    index. Phase 2 intentionally avoids unsafe abbreviation expansion because it
    can break one-to-one offset mapping.
    """

    cfg = {**DEFAULT_PREPROCESS_CONFIG, **dict(config or {})}
    if not isinstance(raw_text, str):
        raise TypeError("raw_text must be a string")

    normalized, norm_to_raw = _build_mapped_view(
        raw_text,
        unicode_form=str(cfg.get("unicode_form", "NFC")),
        lowercase=bool(cfg.get("lowercase_normalized", True)),
        collapse_whitespace=bool(cfg.get("collapse_whitespace", True)),
        no_diacritics=False,
    )
    # Search is currently the same safe normalized view. Future extractor-level
    # expansion can add non-offset-mappable variants separately.
    search, search_to_raw = _build_mapped_view(
        raw_text,
        unicode_form=str(cfg.get("unicode_form", "NFC")),
        lowercase=True,
        collapse_whitespace=bool(cfg.get("collapse_whitespace", True)),
        no_diacritics=False,
    )
    if bool(cfg.get("build_no_diacritics_view", True)):
        no_diacritics, no_diacritics_to_raw = _build_mapped_view(
            raw_text,
            unicode_form=str(cfg.get("unicode_form", "NFC")),
            lowercase=True,
            collapse_whitespace=bool(cfg.get("collapse_whitespace", True)),
            no_diacritics=True,
        )
    else:
        no_diacritics = search
        no_diacritics_to_raw = list(search_to_raw)

    return TextViews(
        raw=raw_text,
        normalized=normalized,
        search=search,
        no_diacritics=no_diacritics,
        norm_to_raw=norm_to_raw,
        search_to_raw=search_to_raw,
        no_diacritics_to_raw=no_diacritics_to_raw,
    )


def normalize_char_for_view(
    ch: str,
    *,
    unicode_form: str = "NFC",
    lowercase: bool = True,
    no_diacritics: bool = False,
) -> str:
    value = unicodedata.normalize(unicode_form, ch)
    if lowercase:
        value = value.lower()
    if no_diacritics:
        value = remove_vietnamese_diacritics(value)
    return value


def _build_mapped_view(
    raw_text: str,
    *,
    unicode_form: str,
    lowercase: bool,
    collapse_whitespace: bool,
    no_diacritics: bool,
) -> tuple[str, list[int]]:
    chars: list[str] = []
    char_map: list[int] = []
    previous_was_space = False

    for raw_index, raw_char in enumerate(raw_text):
        normalized = normalize_char_for_view(
            raw_char,
            unicode_form=unicode_form,
            lowercase=lowercase,
            no_diacritics=no_diacritics,
        )
        if not normalized:
            continue
        for out_char in normalized:
            if out_char.isspace():
                if collapse_whitespace:
                    if previous_was_space:
                        continue
                    chars.append(" ")
                    char_map.append(raw_index)
                    previous_was_space = True
                else:
                    chars.append(out_char)
                    char_map.append(raw_index)
                    previous_was_space = out_char.isspace()
            else:
                chars.append(out_char)
                char_map.append(raw_index)
                previous_was_space = False

    return "".join(chars), char_map
