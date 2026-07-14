from __future__ import annotations

import argparse
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


@dataclass(slots=True)
class SubmissionZipResult:
    pred_dir: Path
    zip_path: Path
    json_count: int
    root_folder: str
    entries: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create output.zip for Viettel AI Race submission.")
    parser.add_argument("--pred-dir", default="outputs/predictions/submission_trial/output", help="Directory containing prediction JSON files.")
    parser.add_argument("--zip-path", default="outputs/submission/output.zip", help="Target zip file path.")
    parser.add_argument("--expected-count", type=int, default=100, help="Expected number of JSON files.")
    parser.add_argument("--root-folder", default="output", help="Folder name inside the zip. ABOUT.md specifies 'output/'.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite target zip if it already exists.")
    args = parser.parse_args()

    result = create_submission_zip(
        pred_dir=_resolve_project_path(args.pred_dir),
        zip_path=_resolve_project_path(args.zip_path),
        expected_count=args.expected_count,
        root_folder=args.root_folder,
        overwrite=args.overwrite,
    )

    print("Submission zip created.")
    print(f"pred_dir: {result.pred_dir}")
    print(f"zip_path: {result.zip_path}")
    print(f"json_count: {result.json_count}")
    print(f"root_folder: {result.root_folder}")
    print(f"first_entries: {result.entries[:5]}")
    return 0


def create_submission_zip(
    *,
    pred_dir: Path,
    zip_path: Path,
    expected_count: int = 100,
    root_folder: str = "output",
    overwrite: bool = False,
) -> SubmissionZipResult:
    json_files = sorted(pred_dir.glob("*.json"), key=lambda item: _natural_stem_key(item.stem))
    if len(json_files) != expected_count:
        raise ValueError(f"Prediction JSON count mismatch: expected {expected_count}, got {len(json_files)} in {pred_dir}")
    missing_stems = [str(index) for index in range(1, expected_count + 1) if not (pred_dir / f"{index}.json").is_file()]
    if missing_stems:
        raise ValueError(f"Missing required prediction files: {', '.join(missing_stems[:20])}")
    if zip_path.exists() and not overwrite:
        raise FileExistsError(f"Zip already exists: {zip_path}. Pass --overwrite to replace it.")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    root_folder = root_folder.strip("/\\") or "output"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in json_files:
            archive.write(path, arcname=f"{root_folder}/{path.name}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
    return SubmissionZipResult(pred_dir=pred_dir, zip_path=zip_path, json_count=len(json_files), root_folder=root_folder, entries=names)


def _natural_stem_key(stem: str) -> tuple[int, int | str]:
    try:
        return (0, int(stem))
    except ValueError:
        return (1, stem)


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())