from __future__ import annotations

from pathlib import Path

from src.config import load_config


REQUIRED_PATH_KEYS = {
    "raw_input_dir",
    "icd10_csv",
    "rxnorm_rff",
    "processed_dir",
    "golden_input_dir",
    "golden_gold_dir",
    "prediction_dir",
    "report_dir",
    "submission_dir",
}


def test_default_config_resolves_paths() -> None:
    config = load_config("configs/default.yaml")

    assert REQUIRED_PATH_KEYS <= set(config.paths)
    for key in REQUIRED_PATH_KEYS:
        assert isinstance(config.path(key), Path)
        assert config.path(key).is_absolute()

