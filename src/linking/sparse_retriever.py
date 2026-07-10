from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from src.data_types import MappingCandidate
from src.linking.terminology_normalizer import (
    normalize_for_lookup,
    normalize_no_diacritics_for_lookup,
    tokenize_for_lookup,
)

try:  # Avoid a hard dependency cycle for callers that only need ICD retrieval.
    from src.linking.rxnorm_index import parse_strength
except Exception:  # pragma: no cover - defensive fallback
    parse_strength = None  # type: ignore[assignment]


TerminologyName = Literal["icd", "rx"]


@dataclass(frozen=True)
class SparseIndexPaths:
    vectorizer_path: Path
    matrix_path: Path


@dataclass
class BM25AliasIndex:
    """Small self-contained BM25 index for terminology aliases.

    The project lists `rank-bm25` in requirements, but this implementation keeps
    Phase 1 usable even when that package is not installed in the active Python
    environment. It stores an inverted index instead of a dense document-token
    matrix, so querying remains fast enough for ICD/RxNorm alias tables.
    """

    doc_count: int
    avgdl: float
    doc_len: np.ndarray
    idf: dict[str, float]
    inverted_index: dict[str, list[tuple[int, int]]]
    k1: float = 1.5
    b: float = 0.75

    @classmethod
    def from_tokenized_corpus(
        cls,
        tokenized_corpus: list[list[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "BM25AliasIndex":
        doc_count = len(tokenized_corpus)
        doc_len = np.asarray([len(tokens) for tokens in tokenized_corpus], dtype=np.float32)
        avgdl = float(doc_len.mean()) if doc_count else 0.0
        document_frequency: Counter[str] = Counter()
        inverted: dict[str, list[tuple[int, int]]] = defaultdict(list)

        for doc_idx, tokens in enumerate(tokenized_corpus):
            counts = Counter(tokens)
            for token, tf in counts.items():
                document_frequency[token] += 1
                inverted[token].append((doc_idx, int(tf)))

        # Robertson/Sparck Jones IDF with +1 to keep all useful terms positive.
        idf = {
            token: math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            for token, df in document_frequency.items()
        }
        return cls(
            doc_count=doc_count,
            avgdl=avgdl,
            doc_len=doc_len,
            idf=idf,
            inverted_index=dict(inverted),
            k1=k1,
            b=b,
        )

    def get_scores(self, query_tokens: list[str]) -> np.ndarray:
        scores = np.zeros(self.doc_count, dtype=np.float32)
        if not query_tokens or self.doc_count == 0 or self.avgdl == 0:
            return scores
        for token in set(query_tokens):
            postings = self.inverted_index.get(token)
            if not postings:
                continue
            idf = self.idf.get(token, 0.0)
            for doc_idx, tf in postings:
                denominator = tf + self.k1 * (1.0 - self.b + self.b * self.doc_len[doc_idx] / self.avgdl)
                scores[doc_idx] += idf * (tf * (self.k1 + 1.0)) / denominator
        return scores


def retrieval_text(alias_norm: object, alias_no_diacritics: object) -> str:
    norm = normalize_for_lookup(alias_norm)
    no_diac = normalize_no_diacritics_for_lookup(alias_no_diacritics)
    if no_diac and no_diac != norm:
        return f"{norm} {no_diac}"
    return norm


def bm25_tokens(alias_norm: object, alias_no_diacritics: object) -> list[str]:
    text = retrieval_text(alias_norm, alias_no_diacritics)
    text = _normalize_compact_drug_units(text)
    tokens = tokenize_for_lookup(text)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if "/" in token or "-" in token:
            expanded.extend(part for part in re.split(r"[/-]+", token) if part)
    return expanded


def _normalize_compact_drug_units(text: str) -> str:
    value = re.sub(
        r"(\d+(?:[\.,]\d+)?)(mg|mcg|g|gm|ml|unit|units|%)\b",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\bmg\s*/\s*ml\b", "mg/ml", value, flags=re.IGNORECASE)
    return value


def build_tfidf_artifacts(
    aliases: pd.DataFrame,
    output_dir: str | Path,
    prefix: TerminologyName,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or {}
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus = [retrieval_text(row.get("alias_norm", ""), row.get("alias_no_diacritics", "")) for _, row in aliases.iterrows()]
    if not corpus:
        raise ValueError(f"Cannot build sparse index for {prefix}: empty alias corpus")
    ngram_range = tuple(cfg.get("ngram_range", (3, 5)))
    vectorizer = TfidfVectorizer(
        analyzer=cfg.get("analyzer", "char_wb"),
        ngram_range=ngram_range,  # type: ignore[arg-type]
        lowercase=bool(cfg.get("lowercase", True)),
        min_df=cfg.get("min_df", 1),
        max_features=cfg.get("max_features"),
    )
    matrix = vectorizer.fit_transform(corpus)
    vectorizer_path = out_dir / f"{prefix}_tfidf.pkl"
    matrix_path = out_dir / f"{prefix}_tfidf_matrix.npz"
    joblib.dump(vectorizer, vectorizer_path)
    sparse.save_npz(matrix_path, matrix)
    return {
        f"{prefix}_tfidf_vectorizer_path": str(vectorizer_path),
        f"{prefix}_tfidf_matrix_path": str(matrix_path),
        f"{prefix}_tfidf_shape": [int(matrix.shape[0]), int(matrix.shape[1])],
    }


def build_bm25_artifacts(
    aliases: pd.DataFrame,
    output_dir: str | Path,
    prefix: TerminologyName,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or {}
    bm25_cfg = cfg.get("bm25", {}) if isinstance(cfg.get("bm25", {}), dict) else {}
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tokenized_corpus = [
        bm25_tokens(row.get("alias_norm", ""), row.get("alias_no_diacritics", ""))
        for _, row in aliases.iterrows()
    ]
    if not tokenized_corpus:
        raise ValueError(f"Cannot build BM25 index for {prefix}: empty alias corpus")
    index = BM25AliasIndex.from_tokenized_corpus(
        tokenized_corpus,
        k1=float(bm25_cfg.get("k1", 1.5)),
        b=float(bm25_cfg.get("b", 0.75)),
    )
    bm25_path = out_dir / f"{prefix}_bm25.pkl"
    joblib.dump(index, bm25_path)
    return {
        f"{prefix}_bm25_path": str(bm25_path),
        f"{prefix}_bm25_shape": [int(index.doc_count), int(len(index.idf))],
    }


def build_and_write_sparse_indices(
    processed_dir: str | Path,
    vector_index_dir: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    processed = Path(processed_dir)
    vector_dir = Path(vector_index_dir) if vector_index_dir else processed / "vector_indices"
    icd_aliases = pd.read_parquet(processed / "icd10_aliases.parquet")
    rx_aliases = pd.read_parquet(processed / "rxnorm_aliases.parquet")
    summary: dict[str, Any] = {}
    summary.update(build_tfidf_artifacts(icd_aliases, vector_dir, "icd", config))
    summary.update(build_tfidf_artifacts(rx_aliases, vector_dir, "rx", config))
    summary.update(build_bm25_artifacts(icd_aliases, vector_dir, "icd", config))
    summary.update(build_bm25_artifacts(rx_aliases, vector_dir, "rx", config))
    return summary


class SparseAliasRetriever:
    def __init__(
        self,
        aliases: pd.DataFrame,
        vectorizer_path: str | Path,
        matrix_path: str | Path,
        *,
        terminology: Literal["ICD10", "RXNORM"],
    ) -> None:
        self.aliases = aliases.reset_index(drop=True)
        self.vectorizer = joblib.load(vectorizer_path)
        self.matrix = sparse.load_npz(matrix_path)
        self.terminology = terminology

    @classmethod
    def from_processed(cls, processed_dir: str | Path, *, kind: TerminologyName) -> "SparseAliasRetriever":
        processed = Path(processed_dir)
        vector_dir = processed / "vector_indices"
        if kind == "icd":
            aliases = pd.read_parquet(processed / "icd10_aliases.parquet")
            return cls(aliases, vector_dir / "icd_tfidf.pkl", vector_dir / "icd_tfidf_matrix.npz", terminology="ICD10")
        aliases = pd.read_parquet(processed / "rxnorm_aliases.parquet")
        return cls(aliases, vector_dir / "rx_tfidf.pkl", vector_dir / "rx_tfidf_matrix.npz", terminology="RXNORM")

    def query(self, query: str, top_k: int = 20) -> list[MappingCandidate]:
        query_text = retrieval_text(query, query)
        query_vector = self.vectorizer.transform([query_text])
        scores = (self.matrix @ query_vector.T).toarray().ravel()
        if scores.size == 0:
            return []
        candidate_count = min(max(top_k * 20, top_k, 50), scores.size)
        top_indices = np.argpartition(-scores, candidate_count - 1)[:candidate_count]
        adjusted_scores = scores.copy()
        for idx in top_indices:
            row = self.aliases.iloc[int(idx)]
            adjusted_scores[int(idx)] = _adjust_sparse_score(
                base_score=float(scores[int(idx)]),
                row=row,
                query=query,
                terminology=self.terminology,
            )
        top_indices = top_indices[np.argsort(-adjusted_scores[top_indices])]
        output: list[MappingCandidate] = []
        seen_codes: set[str] = set()
        for idx in top_indices:
            lexical_score = float(scores[idx])
            final_score = float(adjusted_scores[idx])
            if lexical_score <= 0:
                continue
            row = self.aliases.iloc[int(idx)]
            if self.terminology == "ICD10":
                code = str(row.get("code", ""))
                name = str(row.get("canonical_name_vi") or row.get("canonical_name_en") or row.get("alias", ""))
            else:
                code = str(row.get("rxcui", ""))
                name = str(row.get("alias", ""))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            output.append(
                MappingCandidate(
                    code=code,
                    name=name,
                    terminology=self.terminology,
                    lexical_score=lexical_score,
                    final_score=final_score,
                    metadata={
                        "alias": str(row.get("alias", "")),
                        "alias_source": str(row.get("alias_source", "")),
                        "row_index": int(idx),
                        "sparse_adjustment": final_score - lexical_score,
                    },
                )
            )
            if len(output) >= top_k:
                break
        return output


class BM25AliasRetriever:
    def __init__(
        self,
        aliases: pd.DataFrame,
        bm25_path: str | Path,
        *,
        terminology: Literal["ICD10", "RXNORM"],
    ) -> None:
        self.aliases = aliases.reset_index(drop=True)
        self.index: BM25AliasIndex = joblib.load(bm25_path)
        self.terminology = terminology

    @classmethod
    def from_processed(cls, processed_dir: str | Path, *, kind: TerminologyName) -> "BM25AliasRetriever":
        processed = Path(processed_dir)
        vector_dir = processed / "vector_indices"
        if kind == "icd":
            aliases = pd.read_parquet(processed / "icd10_aliases.parquet")
            return cls(aliases, vector_dir / "icd_bm25.pkl", terminology="ICD10")
        aliases = pd.read_parquet(processed / "rxnorm_aliases.parquet")
        return cls(aliases, vector_dir / "rx_bm25.pkl", terminology="RXNORM")

    def query(self, query: str, top_k: int = 20) -> list[MappingCandidate]:
        query_tokens = bm25_tokens(query, query)
        scores = self.index.get_scores(query_tokens)
        if scores.size == 0:
            return []
        candidate_count = min(max(top_k * 20, top_k, 50), scores.size)
        top_indices = np.argpartition(-scores, candidate_count - 1)[:candidate_count]
        adjusted_scores = scores.copy()
        for idx in top_indices:
            row = self.aliases.iloc[int(idx)]
            adjusted_scores[int(idx)] = _adjust_sparse_score(
                base_score=float(scores[int(idx)]),
                row=row,
                query=query,
                terminology=self.terminology,
            )
        top_indices = top_indices[np.argsort(-adjusted_scores[top_indices])]

        output: list[MappingCandidate] = []
        seen_codes: set[str] = set()
        for idx in top_indices:
            lexical_score = float(scores[idx])
            final_score = float(adjusted_scores[idx])
            if lexical_score <= 0:
                continue
            row = self.aliases.iloc[int(idx)]
            if self.terminology == "ICD10":
                code = str(row.get("code", ""))
                name = str(row.get("canonical_name_vi") or row.get("canonical_name_en") or row.get("alias", ""))
            else:
                code = str(row.get("rxcui", ""))
                name = str(row.get("alias", ""))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            output.append(
                MappingCandidate(
                    code=code,
                    name=name,
                    terminology=self.terminology,
                    lexical_score=lexical_score,
                    final_score=final_score,
                    metadata={
                        "alias": str(row.get("alias", "")),
                        "alias_source": str(row.get("alias_source", "")),
                        "row_index": int(idx),
                        "retriever": "bm25",
                        "sparse_adjustment": final_score - lexical_score,
                    },
                )
            )
            if len(output) >= top_k:
                break
        return output


def _adjust_sparse_score(
    *,
    base_score: float,
    row: pd.Series,
    query: str,
    terminology: Literal["ICD10", "RXNORM"],
) -> float:
    """Small deterministic reranking layer over sparse scores.

    This is intentionally conservative: Phase 1 is still a retrieval baseline,
    but RxNorm dose-bearing queries should prefer clinical-drug aliases with a
    matching strength over ingredient-only aliases.
    """

    if terminology != "RXNORM":
        return base_score

    score = base_score
    query_strength_value: float | None = None
    query_strength_unit: str | None = None
    if parse_strength is not None:
        query_strength_value, query_strength_unit = parse_strength(query)

    row_strength_value = row.get("strength_value")
    row_strength_unit = str(row.get("strength_unit", "") or "")
    row_has_strength = pd.notna(row_strength_value) and row_strength_value != ""
    alias_source = str(row.get("alias_source", ""))
    is_clinical_drug = bool(row.get("is_clinical_drug", False))

    if query_strength_value is not None:
        if row_has_strength:
            try:
                row_strength_float = float(row_strength_value)
            except (TypeError, ValueError):
                row_strength_float = None
            if row_strength_float is not None and abs(row_strength_float - query_strength_value) < 1e-6:
                score += 0.20
                if query_strength_unit and row_strength_unit == query_strength_unit:
                    score += 0.05
            else:
                score -= 0.08
        else:
            score -= 0.12
        if is_clinical_drug:
            score += 0.08
        if alias_source == "ingredient_guess":
            score -= 0.05
    else:
        if is_clinical_drug:
            score -= 0.02

    return max(score, 0.0)
