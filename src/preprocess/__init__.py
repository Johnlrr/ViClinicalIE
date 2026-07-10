"""Raw-preserving preprocessing utilities for Phase 2."""

from src.preprocess.chunker import chunk_text, preprocess_text
from src.preprocess.normalizer import build_text_views
from src.preprocess.offset_mapper import map_view_span_to_raw

__all__ = [
    "build_text_views",
    "chunk_text",
    "map_view_span_to_raw",
    "preprocess_text",
]
