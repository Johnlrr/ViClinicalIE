from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

from src.io_utils import write_json


def _load_make_submission_zip_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "make_submission_zip.py"
    spec = importlib.util.spec_from_file_location("make_submission_zip", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_submission_zip"] = module
    spec.loader.exec_module(module)
    return module


def test_create_submission_zip_uses_output_folder_root(tmp_path) -> None:
    module = _load_make_submission_zip_module()
    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    for index in range(1, 4):
        write_json(pred_dir / f"{index}.json", [])
    zip_path = tmp_path / "output.zip"

    result = module.create_submission_zip(pred_dir=pred_dir, zip_path=zip_path, expected_count=3, overwrite=True)

    assert result.json_count == 3
    with zipfile.ZipFile(zip_path, "r") as archive:
        assert archive.namelist() == ["output/1.json", "output/2.json", "output/3.json"]


def test_create_submission_zip_requires_contiguous_numeric_files(tmp_path) -> None:
    module = _load_make_submission_zip_module()
    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    write_json(pred_dir / "1.json", [])
    write_json(pred_dir / "3.json", [])

    try:
        module.create_submission_zip(pred_dir=pred_dir, zip_path=tmp_path / "output.zip", expected_count=2, overwrite=True)
    except ValueError as exc:
        assert "Missing required prediction files" in str(exc)
    else:
        raise AssertionError("Expected missing contiguous file error")