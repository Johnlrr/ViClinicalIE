from __future__ import annotations

from src.data_types import Chunk
from src.ner.gliner_windows import build_gliner_windows


def test_long_chunk_creates_raw_aligned_overlap_windows() -> None:
    raw = "một hai ba bốn năm sáu"
    chunk = Chunk(raw, 0, len(raw), section="CURRENT")
    windows = build_gliner_windows(raw, [chunk], max_tokens=4, overlap_tokens=2)
    assert len(windows) == 2
    assert windows[0].text == "một hai ba bốn"
    assert windows[1].text == "ba bốn năm sáu"
    assert all(raw[window.start:window.end] == window.text for window in windows)
    assert all(window.section == "CURRENT" for window in windows)