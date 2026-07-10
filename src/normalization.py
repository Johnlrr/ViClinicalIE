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


def _unicode_nfc_view(text: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Return an NFC view whose characters retain spans in the original string."""
    chars: List[str] = []
    sources: List[Tuple[int, int]] = []
    index = 0
    while index < len(text):
        cluster_end = index + 1
        while cluster_end < len(text) and unicodedata.combining(text[cluster_end]):
            cluster_end += 1
        normalized_cluster = unicodedata.normalize("NFC", text[index:cluster_end])
        for char in normalized_cluster:
            chars.append(char)
            sources.append((index, cluster_end))
        index = cluster_end
    return "".join(chars), sources


def normalize_with_mapping(text: str, for_matching: bool = True) -> Tuple[str, List[int], List[int]]:
    """Normalize a lookup view while preserving offsets into the exact input.

    The returned maps are character maps. ``norm_to_raw[i]`` points to the first
    raw character that produced normalized character ``i``. ``raw_to_norm[j]``
    points to a normalized character produced from raw character ``j``, or ``-1``
    when that raw character was stripped. Final entity offsets must always be
    recovered against the original ``text`` argument.
    """
    unicode_text, unicode_sources = _unicode_nfc_view(text)
    norm_chars: List[str] = []
    norm_sources: List[Tuple[int, int]] = []
    replacements = sorted(
        ((unicodedata.normalize("NFC", typo).lower(), unicodedata.normalize("NFC", correct).lower())
         for typo, correct in NOISE_NORMALIZATION.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    index = 0
    while index < len(unicode_text):
        matched = None
        if for_matching:
            lowered_remaining = unicode_text[index:].lower()
            matched = next(
                ((typo, correct) for typo, correct in replacements if lowered_remaining.startswith(typo)),
                None,
            )

        if matched is not None:
            typo, replacement = matched
            source_start = unicode_sources[index][0]
            source_end = unicode_sources[index + len(typo) - 1][1]
            for char in replacement:
                norm_chars.append(char)
                norm_sources.append((source_start, source_end))
            index += len(typo)
            continue

        char = unicode_text[index]
        if for_matching and char.isspace():
            whitespace_start = unicode_sources[index][0]
            whitespace_end = unicode_sources[index][1]
            index += 1
            while index < len(unicode_text) and unicode_text[index].isspace():
                whitespace_end = unicode_sources[index][1]
                index += 1
            norm_chars.append(" ")
            norm_sources.append((whitespace_start, whitespace_end))
            continue

        output = char.lower() if for_matching else char
        for output_char in output:
            norm_chars.append(output_char)
            norm_sources.append(unicode_sources[index])
        index += 1

    if for_matching:
        while norm_chars and norm_chars[-1] == " ":
            norm_chars.pop()
            norm_sources.pop()
        while norm_chars and norm_chars[0] == " ":
            norm_chars.pop(0)
            norm_sources.pop(0)

    norm_to_raw = [source_start for source_start, _ in norm_sources]
    raw_to_norm: List[int] = [-1] * len(text)
    for norm_index, (source_start, source_end) in enumerate(norm_sources):
        for raw_index in range(source_start, source_end):
            if raw_to_norm[raw_index] == -1:
                raw_to_norm[raw_index] = norm_index

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
