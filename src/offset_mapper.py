"""Offset mapping utilities to track character positions through normalization."""

from typing import Tuple, List, Optional
import re

from src.normalization import normalize_with_mapping


class OffsetMapper:
    """
    Maps character offsets between raw and normalized text.
    Critical: ensures raw_text[start:end] == text validation always passes.
    """
    
    def __init__(
        self,
        raw_text: str,
        normalized_text: str = "",
        norm_to_raw_map: Optional[List[int]] = None,
        raw_to_norm_map: Optional[List[int]] = None,
    ):
        """
        Initialize offset mapper.
        
        Args:
            raw_text: Original text (immutable)
            normalized_text: Normalized version of text
        """
        self.raw_text = raw_text
        self.normalized_text = normalized_text
        self.norm_to_raw_map = norm_to_raw_map or []
        self.raw_to_norm_map = raw_to_norm_map or []
        
        # For simple normalization (lowercase, whitespace), mappings are straightforward
        # We'll build character-level mapping if needed
        self._build_mapping()
    
    def _build_mapping(self):
        """Build character-level mapping between raw and normalized text."""
        if self.norm_to_raw_map and self.raw_to_norm_map:
            return

        if not self.normalized_text:
            normalized, norm_to_raw, raw_to_norm = normalize_with_mapping(self.raw_text, for_matching=True)
            self.normalized_text = normalized
            self.norm_to_raw_map = norm_to_raw
            self.raw_to_norm_map = raw_to_norm
            return

        generated, norm_to_raw, raw_to_norm = normalize_with_mapping(self.raw_text, for_matching=True)
        if generated == self.normalized_text:
            self.norm_to_raw_map = norm_to_raw
            self.raw_to_norm_map = raw_to_norm
            return

        if len(self.raw_text) == len(self.normalized_text):
            self.norm_to_raw_map = list(range(len(self.normalized_text)))
            self.raw_to_norm_map = list(range(len(self.raw_text)))
            return

        # Conservative fallback: map the shared prefix and make recovery fail
        # gracefully for out-of-range normalized spans.
        shared_len = min(len(self.raw_text), len(self.normalized_text))
        self.norm_to_raw_map = list(range(shared_len))
        self.raw_to_norm_map = list(range(shared_len)) + [-1] * (len(self.raw_text) - shared_len)

    def recover_raw_span_from_normalized_match(self, norm_start: int, norm_end: int) -> Optional[Tuple[int, int]]:
        """
        Convert a normalized text span to a raw text span.

        Returns None when the normalized span cannot be mapped safely.
        """
        if norm_start < 0 or norm_end > len(self.norm_to_raw_map) or norm_start >= norm_end:
            return None

        # Prefer the reverse map because one normalized character may originate
        # from multiple raw code points (for example decomposed Vietnamese Unicode)
        # or an entire typo-replacement span.
        raw_indices = [
            raw_index
            for raw_index, mapped_norm_index in enumerate(self.raw_to_norm_map)
            if norm_start <= mapped_norm_index < norm_end
        ]
        if raw_indices:
            raw_start = min(raw_indices)
            raw_end = max(raw_indices) + 1
        else:
            mapped_indices = self.norm_to_raw_map[norm_start:norm_end]
            if not mapped_indices:
                return None
            raw_start = min(mapped_indices)
            raw_end = max(mapped_indices) + 1

        if raw_start < 0 or raw_end > len(self.raw_text) or raw_start >= raw_end:
            return None
        return raw_start, raw_end

    def recover_raw_text_from_normalized_match(self, norm_start: int, norm_end: int) -> Optional[str]:
        """Return the raw substring for a normalized match span."""
        raw_span = self.recover_raw_span_from_normalized_match(norm_start, norm_end)
        if raw_span is None:
            return None
        raw_start, raw_end = raw_span
        return self.raw_text[raw_start:raw_end]
    
    def validate_span(self, text: str, start: int, end: int, use_raw: bool = True) -> bool:
        """
        Validate that a span matches the text at given offsets.
        
        Args:
            text: Text to validate
            start: Start offset
            end: End offset
            use_raw: If True, validate against raw_text; if False, against normalized_text
            
        Returns:
            True if validation passes
        """
        source_text = self.raw_text if use_raw else self.normalized_text
        
        # Check bounds
        if start < 0 or end > len(source_text) or start >= end:
            return False
        
        # Extract and compare
        extracted = source_text[start:end]
        return extracted == text
    
    def find_in_raw(self, text: str, start_hint: int = 0, window: int = 50) -> Optional[Tuple[int, int]]:
        """
        Find text in raw_text and return (start, end) offsets.
        Uses exact match with optional case-insensitive fallback.
        
        Args:
            text: Text to find
            start_hint: Approximate starting position
            window: Search window size
            
        Returns:
            (start, end) tuple if found, None otherwise
        """
        # Try exact match first in window
        search_start = max(0, start_hint - window)
        search_end = min(len(self.raw_text), start_hint + len(text) + window)
        search_region = self.raw_text[search_start:search_end]
        
        # Exact match
        pos = search_region.find(text)
        if pos != -1:
            actual_start = search_start + pos
            actual_end = actual_start + len(text)
            return (actual_start, actual_end)
        
        # Try case-insensitive
        text_lower = text.lower()
        pos = search_region.lower().find(text_lower)
        if pos != -1:
            actual_start = search_start + pos
            actual_end = actual_start + len(text)
            # Return original case from raw_text
            return (actual_start, actual_end)
        
        return None
    
    def find_all_in_raw(self, text: str, case_sensitive: bool = False) -> List[Tuple[int, int]]:
        """
        Find all occurrences of text in raw_text.
        
        Args:
            text: Text to find
            case_sensitive: Whether to match case
            
        Returns:
            List of (start, end) tuples
        """
        results = []
        search_text = self.raw_text if case_sensitive else self.raw_text.lower()
        pattern = text if case_sensitive else text.lower()
        
        start = 0
        while True:
            pos = search_text.find(pattern, start)
            if pos == -1:
                break
            results.append((pos, pos + len(text)))
            start = pos + 1
        
        return results


def create_offset_mapper(
    raw_text: str,
    normalized_text: str = "",
    norm_to_raw_map: Optional[List[int]] = None,
    raw_to_norm_map: Optional[List[int]] = None,
) -> OffsetMapper:
    """
    Factory function to create OffsetMapper.
    
    Args:
        raw_text: Original text
        normalized_text: Normalized text
        
    Returns:
        OffsetMapper instance
    """
    return OffsetMapper(raw_text, normalized_text, norm_to_raw_map, raw_to_norm_map)
