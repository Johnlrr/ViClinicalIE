from __future__ import annotations

from src.type_resolution.features import TypeFeatures, build_type_features, has_disease_head, has_drug_context, has_symptom_head
from src.type_resolution.resolver import ResolvedCandidate, TypeConflict, TypeOverlap, TypeResolver

__all__ = [
    "ResolvedCandidate",
    "TypeConflict",
    "TypeOverlap",
    "TypeFeatures",
    "TypeResolver",
    "build_type_features",
    "has_disease_head",
    "has_drug_context",
    "has_symptom_head",
]
