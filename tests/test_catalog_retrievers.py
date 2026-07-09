"""No-network sanity tests for the full-catalog retrievers.

These load the real data resources once per module and assert that the
retrievers surface a plausible code within `top_n` for known spans. They skip
gracefully when a data file is absent so the suite still runs in trimmed
checkouts. No network access is required.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.linking.icd10_catalog import Icd10Catalog
from src.linking.rxnorm_catalog import RxNormCatalog

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIR = ROOT / "data_resources"
ICD_CSV = RESOURCE_DIR / "icd10_byt_source.csv"
RXNORM_RRF = RESOURCE_DIR / "RXNCONSO.RRF"


@pytest.fixture(scope="module")
def icd_catalog() -> Icd10Catalog:
    if not ICD_CSV.exists():
        pytest.skip(f"ICD-10 source not found: {ICD_CSV}")
    return Icd10Catalog.from_csv(ICD_CSV)


@pytest.fixture(scope="module")
def rxnorm_catalog() -> RxNormCatalog:
    if not RXNORM_RRF.exists():
        pytest.skip(f"RXNCONSO.RRF not found: {RXNORM_RRF}")
    return RxNormCatalog.from_rrf(RXNORM_RRF)


def _codes(results):
    return [code for code, _ in results]


def test_icd_only_valid_codes(icd_catalog: Icd10Catalog):
    """Every indexed code matches the ICD code pattern (no header/index rows)."""
    import re

    pattern = re.compile(r"^[A-Z]\d{2}(?:\.\d+)?$")
    assert icd_catalog.entries, "catalog should not be empty"
    for entry in icd_catalog.entries[:2000]:
        assert pattern.match(entry.code), f"bad code leaked in: {entry.code!r}"


def test_icd_hypertension_family(icd_catalog: Icd10Catalog):
    """'tăng huyết áp' should surface an I10-family hypertension code."""
    codes = _codes(icd_catalog.top_n("tăng huyết áp", 10))
    assert codes, "expected a non-empty shortlist"
    assert any(c.startswith("I1") for c in codes), f"no hypertension code in {codes}"


def test_icd_diabetes(icd_catalog: Icd10Catalog):
    """'đái tháo đường' should surface an E10/E11-family diabetes code."""
    codes = _codes(icd_catalog.top_n("đái tháo đường", 10))
    assert any(c.startswith("E1") for c in codes), f"no diabetes code in {codes}"


def test_rxnorm_amlodipine(rxnorm_catalog: RxNormCatalog):
    """'amlodipine 10 mg' should surface amlodipine's ingredient cui (17767)."""
    codes = _codes(rxnorm_catalog.top_n("amlodipine 10 mg", 10))
    assert codes, "expected a non-empty shortlist"
    assert "17767" in codes, f"amlodipine ingredient cui missing from {codes}"


def test_rxnorm_metoprolol_span(rxnorm_catalog: RxNormCatalog):
    """A real drug span with dose/route/freq should still find metoprolol (6918)."""
    codes = _codes(rxnorm_catalog.top_n("metoprolol 25mg po bid", 10))
    assert "6918" in codes, f"metoprolol ingredient cui missing from {codes}"
