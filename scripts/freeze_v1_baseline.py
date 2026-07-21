from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.io_utils import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze and verify two completed V1 prediction runs.")
    parser.add_argument("--run1", required=True)
    parser.add_argument("--run2", required=True)
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--input-dir", default="data/golden/input")
    parser.add_argument("--gold-dir", default="data/golden/gold")
    parser.add_argument("--output", default="outputs/baselines/v1_frozen/artifact_manifest.json")
    args = parser.parse_args()
    run1, run2 = Path(args.run1), Path(args.run2)
    first, second = _directory_manifest(run1), _directory_manifest(run2)
    if set(first) != set(second):
        raise ValueError("Prediction file sets differ between baseline runs")
    mismatches = [name for name in first if first[name] != second[name]]
    manifest = {
        "baseline_id": "V1_FROZEN",
        "git_commit": _git_commit(),
        "config": _file_entry(Path(args.config)),
        "input": _directory_manifest(Path(args.input_dir), pattern="*.txt"),
        "gold": _directory_manifest(Path(args.gold_dir)),
        "run1": first,
        "run2": second,
        "byte_identical": not mismatches,
        "mismatched_files": mismatches,
        "environment": _environment(),
    }
    write_json(args.output, manifest)
    if mismatches:
        raise ValueError(f"Baseline runs are not byte-identical: {mismatches[:5]}")
    print(f"V1_FROZEN verified: {len(first)} byte-identical files")
    return 0


def _directory_manifest(directory: Path, pattern: str = "*.json") -> dict[str, str]:
    return {path.name: _sha256(path) for path in sorted(directory.glob(pattern))}


def _file_entry(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()


def _environment() -> dict:
    packages = {}
    for name in ("numpy", "pandas", "scikit-learn", "pyyaml", "torch"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


if __name__ == "__main__":
    raise SystemExit(main())