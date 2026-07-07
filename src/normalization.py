"""Text normalization utilities that preserve offset mapping."""

import unicodedata
import re
from typing import Dict, List, Tuple


# Noise normalization map for common typos
NOISE_NORMALIZATION = {
    "hin tại": "hiện tại",
    "Kêt quả": "Kết quả",
    "nhaoaj viện": "nhập viện",
    "sau khí": "sau khi",
    "cơni": "cơn",
    "morphineiv morphine": "morphine",
    "atenololtrong": "atenolol trong",
    "doxycyclinebactrim": "doxycycline bactrim",
    "albuterolipratropium": "albuterol ipratropium",
    "cảm giáckhó chịu": "cảm giác khó chịu",
    "bình thườngbình thường": "bình thường",
}


def normalize_text(text: str, for_matching: bool = False) -> str:
    """
    Normalize text for processing.
    
    Args:
        text: Input text
        for_matching: If True, apply aggressive normalization for matching
                     If False, apply minimal normalization
                     
    Returns:
        Normalized text
    """
    # Unicode normalization (NFC form)
    text = unicodedata.normalize('NFC', text)
    
    if for_matching:
        # Aggressive normalization for dictionary/regex matching
        
        # Lowercase
        text = text.lower()
        
        # Apply noise normalization
        for typo, correct in NOISE_NORMALIZATION.items():
            text = text.replace(typo.lower(), correct.lower())
        
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text)
        
        # Strip leading/trailing whitespace
        text = text.strip()
    
    else:
        # Minimal normalization for display/output
        # Just collapse excessive whitespace
        text = re.sub(r'\s+', ' ', text)
    
    return text


def _replacement_raw_index(raw_start: int, raw_len: int, replacement_len: int, replacement_index: int) -> int:
    """Map one replacement character back into the raw matched span."""
    if raw_len <= 1 or replacement_len <= 1:
        return raw_start
    return raw_start + round(replacement_index * (raw_len - 1) / (replacement_len - 1))


def normalize_with_mapping(text: str, for_matching: bool = True) -> Tuple[str, List[int], List[int]]:
    """
    Normalize text while preserving a normalized-index to raw-index map.

    This is intended for matching only. Any final output must recover the raw
    substring through the returned mapping before writing `text` and `position`.
    """
    raw_text = unicodedata.normalize('NFC', text)
    norm_chars: List[str] = []
    norm_to_raw: List[int] = []
    raw_to_norm: List[int] = [-1] * len(raw_text)

    replacements = sorted(
        ((typo.lower(), correct.lower()) for typo, correct in NOISE_NORMALIZATION.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    i = 0
    while i < len(raw_text):
        raw_char = raw_text[i]

        if for_matching:
            lowered_remaining = raw_text[i:].lower()
            matched = None
            for typo, correct in replacements:
                if lowered_remaining.startswith(typo):
                    matched = (typo, correct)
                    break

            if matched:
                typo, correct = matched
                raw_len = len(typo)
                start_norm = len(norm_chars)
                for j, out_char in enumerate(correct):
                    norm_chars.append(out_char)
                    norm_to_raw.append(_replacement_raw_index(i, raw_len, len(correct), j))
                for raw_index in range(i, min(i + raw_len, len(raw_text))):
                    raw_to_norm[raw_index] = start_norm
                i += raw_len
                continue

        if for_matching and raw_char.isspace():
            whitespace_start = i
            while i < len(raw_text) and raw_text[i].isspace():
                i += 1
            if norm_chars and norm_chars[-1] != " ":
                norm_index = len(norm_chars)
                norm_chars.append(" ")
                norm_to_raw.append(whitespace_start)
                for raw_index in range(whitespace_start, i):
                    raw_to_norm[raw_index] = norm_index
            continue

        out_char = raw_char.lower() if for_matching else raw_char
        norm_index = len(norm_chars)
        norm_chars.append(out_char)
        norm_to_raw.append(i)
        raw_to_norm[i] = norm_index
        i += 1

    if for_matching:
        while norm_chars and norm_chars[-1] == " ":
            norm_chars.pop()
            norm_to_raw.pop()
        while norm_chars and norm_chars[0] == " ":
            norm_chars.pop(0)
            norm_to_raw.pop(0)
            raw_to_norm = [idx - 1 if idx > 0 else idx for idx in raw_to_norm]

    return "".join(norm_chars), norm_to_raw, raw_to_norm


def normalize_for_display(text: str) -> str:
    """Minimal normalization for display/output."""
    return normalize_text(text, for_matching=False)


def normalize_for_matching(text: str) -> str:
    """Aggressive normalization for matching."""
    normalized, _, _ = normalize_with_mapping(text, for_matching=True)
    return normalized


def get_noise_normalization_map() -> Dict[str, str]:
    """Get the noise normalization mapping."""
    return NOISE_NORMALIZATION.copy()


def add_noise_normalization(typo: str, correct: str):
    """Add a new typo->correct mapping."""
    NOISE_NORMALIZATION[typo] = correct


def normalize_vietnamese_diacritics(text: str) -> str:
    """
    Remove Vietnamese diacritics for fuzzy matching.
    
    Args:
        text: Input text with diacritics
        
    Returns:
        Text without diacritics
    """
    # Decompose Vietnamese characters
    text = unicodedata.normalize('NFD', text)
    
    # Remove combining characters (diacritics)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    
    # Normalize back
    text = unicodedata.normalize('NFC', text)
    
    return text
