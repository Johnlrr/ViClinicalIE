from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    config_path: Path
    raw: dict[str, Any]
    paths: dict[str, Path]

    def path(self, key: str) -> Path:
        try:
            return self.paths[key]
        except KeyError as exc:
            known = ", ".join(sorted(self.paths))
            raise KeyError(f"Unknown path key '{key}'. Known keys: {known}") from exc

    def to_serializable(self) -> dict[str, Any]:
        data = dict(self.raw)
        data["paths"] = {key: str(path) for key, path in self.paths.items()}
        data["project_root"] = str(self.project_root)
        data["config_path"] = str(self.config_path)
        return data


def load_yaml(path: str | Path) -> dict[str, Any]:
    yaml_path = Path(path)
    with yaml_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {yaml_path}")
    return data


def load_config(
    config_path: str | Path = "configs/default.yaml",
    project_root: str | Path | None = None,
) -> AppConfig:
    root = Path(project_root).resolve() if project_root else PROJECT_ROOT
    resolved_config = _resolve_path(config_path, root).resolve()
    config_data = _load_config_with_extends(resolved_config)

    paths_config_value = config_data.get("paths_config")
    paths_data: dict[str, Any] = {}
    if paths_config_value:
        paths_config_path = _resolve_path(paths_config_value, resolved_config.parent)
        paths_data = load_yaml(paths_config_path)
        if "paths" in paths_data and isinstance(paths_data["paths"], dict):
            paths_data = paths_data["paths"]

    inline_paths = config_data.get("paths", {})
    if inline_paths and not isinstance(inline_paths, Mapping):
        raise ValueError("'paths' in config must be a mapping")

    merged_paths = {**paths_data, **dict(inline_paths)}
    resolved_paths = {
        key: _resolve_path(value, root)
        for key, value in merged_paths.items()
    }

    raw = dict(config_data)
    raw["paths"] = {key: str(value) for key, value in merged_paths.items()}

    return AppConfig(
        project_root=root,
        config_path=resolved_config,
        raw=raw,
        paths=resolved_paths,
    )


def _load_config_with_extends(path: Path, stack: tuple[Path, ...] = ()) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(item) for item in (*stack, resolved))
        raise ValueError(f"Circular config extends chain: {chain}")
    data = load_yaml(resolved)
    parent_value = data.pop("extends", None)
    if not parent_value:
        return data
    parent_path = _resolve_path(parent_value, resolved.parent).resolve()
    parent = _load_config_with_extends(parent_path, (*stack, resolved))
    return _deep_merge(parent, data)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _resolve_path(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return base_dir / path

