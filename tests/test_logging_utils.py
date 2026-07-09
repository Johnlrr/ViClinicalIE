from __future__ import annotations

from src.io_utils import read_json
from src.logging_utils import DEFAULT_LOG_FILES, create_run_report_dir


def test_create_run_report_dir(tmp_path) -> None:
    run_dir = create_run_report_dir(
        tmp_path,
        {"phase": "test"},
        timestamp="20260709_000000",
        run_name="unit",
    )

    assert run_dir.is_dir()
    assert (run_dir / "config.yaml").is_file()
    assert (run_dir / "summary.json").is_file()
    assert read_json(run_dir / "summary.json")["status"] == "initialized"

    for log_file in DEFAULT_LOG_FILES:
        path = run_dir / log_file
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == ""

