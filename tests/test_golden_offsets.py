from __future__ import annotations

from src.config import load_config
from src.io_utils import read_json, read_text


def test_golden_offsets_match_raw_text() -> None:
    config = load_config("configs/default.yaml")

    for item_id in range(1, 21):
        raw_text = read_text(config.path("golden_input_dir") / f"{item_id}.txt")
        entities = read_json(config.path("golden_gold_dir") / f"{item_id}.json")

        assert isinstance(entities, list)
        for entity in entities:
            start, end = entity["position"]
            assert raw_text[start:end] == entity["text"]

