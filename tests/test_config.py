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


def test_config_extends_deep_merges_parent(tmp_path) -> None:
    parent = tmp_path / "parent.yaml"
    child = tmp_path / "child.yaml"
    parent.write_text("paths:\n  raw_input_dir: raw\nfeature:\n  enabled: false\n  threshold: 0.5\n", encoding="utf-8")
    child.write_text("extends: parent.yaml\nfeature:\n  enabled: true\n", encoding="utf-8")

    config = load_config(child, project_root=tmp_path)

    assert config.raw["feature"] == {"enabled": True, "threshold": 0.5}
    assert config.path("raw_input_dir") == tmp_path / "raw"

