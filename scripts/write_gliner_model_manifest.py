from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a reproducibility manifest for a provisioned Hugging Face GLiNER cache.")
    parser.add_argument("--cache-dir", default=str(Path.home() / ".cache" / "huggingface" / "hub" / "models--urchade--gliner_multi-v2.1"))
    parser.add_argument("--model", default="urchade/gliner_multi-v2.1")
    parser.add_argument("--output", default="outputs/reports/v2_ner1_gliner_reproduction/model_manifest.json")
    args = parser.parse_args()
    cache = Path(args.cache_dir)
    revision = (cache / "refs" / "main").read_text(encoding="utf-8").strip()
    snapshot = cache / "snapshots" / revision
    if not snapshot.is_dir():
        raise FileNotFoundError(f"Missing GLiNER snapshot: {snapshot}")
    incomplete = list(cache.rglob("*.incomplete"))
    if incomplete:
        raise RuntimeError(f"GLiNER cache is incomplete: {[path.name for path in incomplete]}")
    files = {}
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(snapshot)).replace(os.sep, "/")] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    packages = {}
    for name in ("torch", "transformers", "gliner", "safetensors"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "model": args.model,
        "revision": revision,
        "snapshot_path": str(snapshot),
        "files": files,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": packages,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"model manifest written: revision={revision} files={len(files)}")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())