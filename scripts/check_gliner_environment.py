from __future__ import annotations

import importlib.metadata
import json
import platform
import sys


def main() -> int:
    packages = ("torch", "transformers", "gliner", "safetensors")
    versions = {}
    missing = []
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
            missing.append(package)
    print(json.dumps({"python": sys.version, "platform": platform.platform(), "packages": versions}, indent=2))
    if missing:
        print(f"missing required packages: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())