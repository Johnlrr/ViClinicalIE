from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_text(path: str | Path, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding=encoding)


def read_json(path: str | Path, encoding: str = "utf-8") -> Any:
    return json.loads(read_text(path, encoding=encoding))


def write_json(
    path: str | Path,
    data: Any,
    encoding: str = "utf-8",
    indent: int = 2,
) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    write_text(path, f"{text}\n", encoding=encoding)


def append_jsonl(path: str | Path, data: Any, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding=encoding) as handle:
        handle.write(json.dumps(data, ensure_ascii=False))
        handle.write("\n")

