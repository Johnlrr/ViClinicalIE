from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.extractors.base import BaseExtractor, ExtractionContext
from src.extractors.dictionary_extractor import DictionaryExtractor
from src.extractors.drug_extractor import DrugExtractor
from src.extractors.imaging_extractor import ImagingExtractor
from src.extractors.lab_extractor import LabExtractor
from src.extractors.ner_extractor import NERExtractor
from src.extractors.problem_extractor import ProblemExtractor


def build_default_extractors(config: AppConfig) -> list[BaseExtractor]:
    extractor_cfg: dict[str, Any] = dict(config.raw.get("extractors", {}))
    extractors: list[BaseExtractor] = []

    if extractor_cfg.get("dictionary", {}).get("enabled", True):
        paths: list[Path] = []
        for key in ("symptoms_csv",):
            if key in config.paths and config.path(key).exists():
                paths.append(config.path(key))
        extractors.append(DictionaryExtractor(dictionary_paths=paths, config=extractor_cfg.get("dictionary", {})))

    if extractor_cfg.get("drug", {}).get("enabled", True):
        extractors.append(
            DrugExtractor(
                rxnorm_alias_path=config.path("processed_dir") / "rxnorm_aliases.parquet",
                manual_alias_path=config.path("drug_aliases_csv") if "drug_aliases_csv" in config.paths else None,
                config=extractor_cfg.get("drug", {}),
            )
        )

    if extractor_cfg.get("lab", {}).get("enabled", True):
        extractors.append(
            LabExtractor(
                lab_tests_path=config.path("lab_tests_csv") if "lab_tests_csv" in config.paths else None,
                config=extractor_cfg.get("lab", {}),
            )
        )

    if extractor_cfg.get("imaging", {}).get("enabled", True):
        extractors.append(ImagingExtractor(config=extractor_cfg.get("imaging", {})))

    if extractor_cfg.get("problem", {}).get("enabled", True):
        extractors.append(ProblemExtractor(config=extractor_cfg.get("problem", {})))

    if extractor_cfg.get("ner", {}).get("enabled", False):
        extractors.append(NERExtractor(config=extractor_cfg.get("ner", {})))

    return extractors


__all__ = [
    "BaseExtractor",
    "DictionaryExtractor",
    "DrugExtractor",
    "ExtractionContext",
    "ImagingExtractor",
    "LabExtractor",
    "NERExtractor",
    "ProblemExtractor",
    "build_default_extractors",
]
