from __future__ import annotations

from src.preprocess.chunker import chunk_text, preprocess_text


def test_chunk_text_preserves_raw_slices_for_lines_and_bullets() -> None:
    raw = "Lý do nhập viện: ho.\n1. aspirin 81 mg po daily\n- sốt nhẹ"
    chunks = chunk_text(raw, {"max_chunk_chars": 500})

    assert len(chunks) == 3
    for chunk in chunks:
        assert raw[chunk.start:chunk.end] == chunk.text
    assert chunks[1].bullet_level == 2
    assert chunks[2].bullet_level == 1


def test_chunk_text_splits_long_lines_without_breaking_offsets() -> None:
    raw = "A" * 120 + ". " + "B" * 120
    chunks = chunk_text(raw, {"max_chunk_chars": 80})

    assert len(chunks) >= 2
    for chunk in chunks:
        assert raw[chunk.start:chunk.end] == chunk.text


def test_preprocess_text_returns_views_and_chunks() -> None:
    raw = "Bệnh nhân ho sốt\nKhông đau ngực"
    output = preprocess_text(raw, {"preprocess": {}, "chunking": {}})

    assert output.raw_text == raw
    assert output.views.raw == raw
    assert output.chunks
    for chunk in output.chunks:
        assert raw[chunk.start:chunk.end] == chunk.text
