from __future__ import annotations

from src.config import load_config


def test_canonical_data_layout_exists() -> None:
    config = load_config("configs/default.yaml")

    raw_inputs = sorted(config.path("raw_input_dir").glob("*.txt"))
    golden_inputs = sorted(config.path("golden_input_dir").glob("*.txt"))
    golden_gold = sorted(config.path("golden_gold_dir").glob("*.json"))

    assert len(raw_inputs) == 100
    assert len(golden_inputs) == 20
    assert len(golden_gold) == 20
    assert config.path("icd10_csv").is_file()
    assert config.path("rxnorm_rff").is_file()


def test_golden_pairs_are_numbered_1_to_20() -> None:
    config = load_config("configs/default.yaml")

    for item_id in range(1, 21):
        assert (config.path("golden_input_dir") / f"{item_id}.txt").is_file()
        assert (config.path("golden_gold_dir") / f"{item_id}.json").is_file()

