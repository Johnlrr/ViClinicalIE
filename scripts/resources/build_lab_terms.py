"""Build curated lab dictionary resources from two PDFs + abbreviation.txt.

This is a one-off resource-building script for the rebuilt lab_parser resource
layer, implementing ``plans/11_7_26/1_plan_update_lab_seeds.md``.

Pipeline (three ordered stages):

1. Combine ``lab_med_ministry.pdf`` (official biochemical procedure list, the
   preferred canonical source) and ``lab_list.pdf`` (hospital catalog, local
   alias enrichment) into ``combined_lab_catalog.csv``.
2. Extract lab-name aliases from the combined PDF catalog *first*
   (concise names, prefix-stripped official names, parenthetical aliases and
   orthographic variants).
3. Check ``abbreviation.txt`` only as a supplemental alias source, linking
   accepted abbreviations back to a PDF-derived ``canonical_key`` when possible.

Final parser-facing outputs:

* ``data_resources/lab_terms_curated.csv``
* ``data_resources/lab_canonical_map.csv``

Intermediate/traceable outputs (under ``data_resources/generated/``):

* ``combined_lab_catalog.csv``
* ``pdf_alias_links.csv``
* ``lab_terms_candidates.csv``
* ``lab_terms_rejected.csv``
* ``abbreviation_alias_links.csv``

Run: ``python -m scripts.resources.build_lab_terms`` (from repo root).
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "pdfplumber is required to build lab resources: pip install pdfplumber"
    ) from exc

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data_resources"
GENERATED_DIR = DATA_DIR / "generated"

MINISTRY_PDF = DATA_DIR / "lab_med_ministry.pdf"
LAB_LIST_PDF = DATA_DIR / "lab_list.pdf"
ABBREVIATION_TXT = DATA_DIR / "abbreviation.txt"

# Ministry biochemical procedure list lives on pages 2-7 (1-based).
MINISTRY_PAGE_INDICES = range(1, 7)  # 0-based indices for pages 2..7

# Procedure prefixes to strip to derive match aliases from official names.
PROCEDURE_PREFIXES = (
    "định lượng",
    "định tính",
    "đo hoạt độ",
    "đo tỷ trọng",
    "điện di",
    "xét nghiệm",
    "tổng phân tích",
    "phản ứng",
    "nghiệm pháp",
)

# Specimen mapping for ministry section headers.
MINISTRY_SECTIONS = {
    "A": ("máu", "blood"),
    "B": ("nước tiểu", "urine"),
    "C": ("dịch não tuỷ", "csf"),
    "D": ("thủy dịch mắt", "eye_fluid"),
    "E": ("dịch chọc dò", "puncture_fluid"),
}


# ---------------------------------------------------------------------------
# Curation allow/block lists for abbreviation.txt (supplemental stage)
# ---------------------------------------------------------------------------

# Non-lab abbreviations to reject even if medically meaningful.
ABBREV_BLOCKLIST = {
    "ace", "aids", "bcg", "bid", "bp", "cns", "copd", "cpr", "ct", "d&c",
    "d & c", "dna", "dtp", "ecg", "eeg", "ent", "ercp", "fda", "gi", "gu",
    "icu", "im", "iv", "ivu", "mri", "nsaid", "otc", "pet", "po", "prn",
    "ra", "rna", "sle", "ssri", "tb", "tpn", "uri", "uti", "who", "hiv",
    "adh", "atp", "bmr", "bsa", "camp", "cgy", "ci", "cu", "d/w", "ecf",
    "f", "ft", "fuo", "gfr", "hcl", "hg", "hla", "hmg-coa", "hz", "icf",
    "iga", "il", "ippb", "kcal", "lb", "m", "mci", "mi", "mic", "mo",
    "mol wt", "mosm", "n", "nacl", "npo", "oz", "pas", "pco2", "pcr", "ppd",
    "q", "qid", "sbe", "sc", "si", "sids", "soln", "sp", "spp", "sp gr",
    "sq", "sts", "wt", "paco2", "pao2", "po2",
}

# Pure units to reject as lab-name aliases.
ABBREV_UNIT_BLOCKLIST = {
    "cm", "dl", "g", "h", "iu", "kg", "l", "meq", "mg", "miu", "ml", "mm",
    "mmol", "ng", "nm", "nmol", "pg", "ppm", "μg", "μl", "μm", "μmol",
    "cgy", "mci",
}

# Short/ambiguous aliases that must be context-gated (requires_context=true).
CONTEXT_REQUIRED = {
    "k", "ca", "cl", "mg", "na", "pt", "ph", "cr", "ck", "hb", "hct",
    "n", "o2", "p", "c", "co2", "hco3", "tt", "rf",
}

# Supplemental abbreviation -> canonical_key link map. Only abbreviations that
# add a *missing* lab-name alias and can be linked to a PDF-derived canonical
# concept are accepted. Keys are lower-cased abbreviations from abbreviation.txt.
ABBREV_CANONICAL_LINKS = {
    "abg": "khi_mau",
    "bun": "ure",
    "hb": "hemoglobin",
    "hct": "hematocrit",
    "esr": "mau_lang",
    "ldh": "ldh",
    "mch": "mch",
    "mchc": "mchc",
    "mcv": "mcv",
    "pt": "pt",
    "ptt": "aptt",
    "g6pd": "g6pd",
    "hco3": "bicarbonate",
    "co2": "co2",
    "sao2": "sao2",
    "pmn": "pmn",
    "acth": "acth",
    "ck": "ck",
    "ck-mb": "ck_mb",
    "ca": "calci",
    "cl": "clo",
    "mg": "magie",
    "na": "natri",
    "k": "kali",
    "ph": "ph",
    "cbc": "cong_thuc_mau",
    "inr": "inr",
    "rbc": "hong_cau",
    "wbc": "bach_cau",
}

# Abbreviation -> extra alias surface forms to emit (beyond the abbr token).
ABBREV_EXTRA_ALIASES = {
    "abg": ["ABG", "khí máu động mạch"],
    "bun": ["BUN"],
    "hb": ["Hb", "hemoglobin"],
    "hct": ["Hct"],
    "esr": ["ESR"],
    "ldh": ["LDH"],
    "mch": ["MCH"],
    "mchc": ["MCHC"],
    "mcv": ["MCV"],
    "pt": ["PT"],
    "ptt": ["PTT"],
    "g6pd": ["G6PD"],
    "hco3": ["HCO3", "bicarbonate"],
    "co2": ["CO2"],
    "sao2": ["SaO2"],
    "pmn": ["PMN"],
    "ca": ["Ca"],
    "cl": ["Cl"],
    "mg": ["Mg"],
    "na": ["Na"],
    "k": ["K"],
    "ph": ["pH"],
}


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_typography(text: str) -> str:
    """Normalize whitespace, greek letters, dashes and casing artifacts."""
    text = text.replace("\u00a0", " ")
    text = (
        text.replace("α", "alpha ")
        .replace("β", "beta ")
        .replace("–", "-")
        .replace("—", "-")
        .replace("≤", "<=")
        .replace("≥", ">=")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonical_key_for(name: str) -> str:
    """Derive a stable ascii grouping key from a normalized lab name."""
    base = _strip_accents(name.lower())
    base = base.replace("&", " and ")
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    return base

CATEGORY_KEYWORDS = (
    ("tumor_marker", (
        "afp", "cea", "ca 19", "ca 72", "ca 15", "ca 125", "psa", "cyfra",
        "nse", "he4", "scc", "progrp", "pro-grp", "beta crosslap",
    )),
    ("coagulation", (
        "d-dimer", "d dimer", "aptt", "pt", "tt", "fibrinogen", "prothrombin",
        "thromboplastin", "inr", "rotem", "extem", "intem", "fibtem",
    )),
    ("hematology", (
        "công thức máu", "huyết đồ", "máu lắng", "hong cau", "hồng cầu",
        "bạch cầu", "hemoglobin", "hematocrit", "mch", "mcv", "wbc", "rbc",
        "hgb", "hct", "plt", "g6pd", "pmn",
    )),
    ("blood_gas", (
        "khí máu", "khi mau", "abg", "sao2", "pco2", "po2", "hco3",
    )),
    ("immunology", (
        "hbsag", "anti-hcv", "anti hcv", "anti-ccp", "aslo", "rf", "ana",
        "dsdna", "coombs", "crp", "pct", "procalcitonin", "hbs",
    )),
    ("microbiology", (
        "pcr", "vi sinh", "cấy", "nhuộm", "kháng sinh đồ",
    )),
    ("endocrine", (
        "tsh", "ft3", "ft4", "t3", "t4", "acth", "cortisol", "hcg", "lh",
        "fsh", "estradiol", "progesteron", "testosterol", "pth", "prolactin",
        "insulin", "hormone", "hormon",
    )),
)


def classify_category(name: str, specimen: str) -> str:
    """Best-effort category from the normalized name and specimen."""
    lowered = name.lower()
    ascii_low = _strip_accents(lowered)
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in lowered or _strip_accents(kw) in ascii_low:
                return category
    if specimen == "urine":
        return "urinalysis"
    return "chemistry"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CatalogRow:
    """One extracted PDF lab/procedure entry (pre-alias enrichment)."""

    source_pdf: str
    source_page: int
    source_item: str
    raw_name: str
    normalized_name: str
    canonical_key: str
    canonical_name: str
    category: str
    specimen: str
    official_name: str = ""
    local_name: str = ""
    notes: str = ""


@dataclass
class AliasRow:
    """One alias-level matching entry for the curated dictionary."""

    term: str
    canonical_key: str
    canonical_name: str
    source: str
    source_detail: str
    category: str
    specimen: str
    requires_context: bool
    priority: int
    notes: str = ""


# ---------------------------------------------------------------------------
# Alias derivation helpers
# ---------------------------------------------------------------------------

def strip_procedure_prefix(raw_name: str) -> str:
    """Remove a leading procedure verb (Định lượng, Đo hoạt độ, ...)."""
    text = normalize_typography(raw_name)
    lowered = text.lower()
    for prefix in PROCEDURE_PREFIXES:
        if lowered.startswith(prefix + " "):
            return text[len(prefix) + 1:].strip()
    return text


def split_parenthetical(name: str) -> Tuple[str, List[str]]:
    """Split ``CEA (carcino embryonic antigen)`` -> ("CEA", ["carcino ..."]).

    Returns the core name (parentheses removed) and the list of parenthetical
    alias fragments.
    """
    aliases: List[str] = []
    for match in re.finditer(r"\(([^)]*)\)", name):
        fragment = match.group(1).strip()
        if fragment:
            aliases.append(fragment)
    core = re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()
    core = re.sub(r"\s+", " ", core)
    return core, aliases


# Orthographic variant rules: map surface substrings to alternative spellings.
VARIANT_RULES = (
    ("urê", "ure"),
    ("ure", "urê"),
    ("canxi", "calci"),
    ("calci", "canxi"),
    ("creatinin", "creatinine"),
    ("ferritin", "feritin"),
    ("feritin", "ferritin"),
    ("phospho", "photpho"),
    ("photpho", "phospho"),
    ("magiê", "magie"),
    ("magie", "magiê"),
    ("hba1c", "hba1c"),
    ("d-dimer", "d dimer"),
    ("crp hs", "crphs"),
    ("crphs", "crp hs"),
    ("nt-probnp", "nt probnp"),
)


def orthographic_variants(term: str) -> List[str]:
    """Generate spelling/orthographic variants for a term."""
    variants: set[str] = set()
    lowered = term.lower()
    for src, dst in VARIANT_RULES:
        if src in lowered:
            variants.add(re.sub(re.escape(src), dst, lowered))
    # ascii-only fold (drop diacritics) as an additional match surface
    folded = _strip_accents(lowered)
    if folded != lowered:
        variants.add(folded)
    variants.discard(lowered)
    return sorted(variants)


# ---------------------------------------------------------------------------
# Stage 1a: extract ministry PDF (official biochemical procedure list)
# ---------------------------------------------------------------------------

# A numbered procedure line, e.g. "51 Định lượng Creatinin". The item number
# may also trail on its own line in the source; we handle the common inline form.
_MINISTRY_ITEM_RE = re.compile(r"^\s*(\d{1,3})\s+(.*\S)\s*$")
_SECTION_HDR_RE = re.compile(r"^\s*([A-E])\.\s+(.+?)\s*$")


def extract_ministry_rows() -> List[CatalogRow]:
    """Parse pages 2-7 of the ministry PDF into catalog rows."""
    rows: List[CatalogRow] = []
    specimen = "blood"  # section A. MÁU is first
    with pdfplumber.open(str(MINISTRY_PDF)) as pdf:
        for page_index in MINISTRY_PAGE_INDICES:
            if page_index >= len(pdf.pages):
                break
            text = pdf.pages[page_index].extract_text() or ""
            for line in text.splitlines():
                stripped = line.strip()
                hdr = _SECTION_HDR_RE.match(stripped)
                if hdr and hdr.group(1) in MINISTRY_SECTIONS:
                    specimen = MINISTRY_SECTIONS[hdr.group(1)][1]
                    continue
                m = _MINISTRY_ITEM_RE.match(stripped)
                if not m:
                    continue
                item_no, raw_name = m.group(1), m.group(2)
                # Skip stray page-footer numbers / summary lines.
                if raw_name.lower().startswith(("tổng số", "kt.", "thứ tr")):
                    continue
                normalized = normalize_typography(raw_name)
                core = strip_procedure_prefix(raw_name)
                core_no_paren, _ = split_parenthetical(core)
                canonical_name = core_no_paren or core
                key = canonical_key_for(canonical_name)
                if not key:
                    continue
                category = classify_category(canonical_name, specimen)
                rows.append(
                    CatalogRow(
                        source_pdf="lab_med_ministry_pdf",
                        source_page=page_index + 1,
                        source_item=item_no,
                        raw_name=normalized,
                        normalized_name=core,
                        canonical_key=key,
                        canonical_name=canonical_name,
                        category=category,
                        specimen=specimen,
                        official_name=core,
                    )
                )
    return rows


# ---------------------------------------------------------------------------
# Stage 1b: extract lab_list PDF (local hospital catalog)
# ---------------------------------------------------------------------------

_LOCAL_SECTION_MARKERS = (
    ("hoá sinh", "chemistry", "blood"),
    ("hóa sinh", "chemistry", "blood"),
    ("miễn dịch", "immunology", "blood"),
    ("vi sinh", "microbiology", "unknown"),
    ("huyết học", "hematology", "blood"),
    ("đông máu", "coagulation", "blood"),
)


def extract_lab_list_rows() -> List[CatalogRow]:
    """Parse the hospital catalog tables into catalog rows."""
    rows: List[CatalogRow] = []
    specimen = "blood"
    with pdfplumber.open(str(LAB_LIST_PDF)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_text = (page.extract_text() or "").lower()
            for marker, _cat, spec in _LOCAL_SECTION_MARKERS:
                if marker in page_text:
                    specimen = spec
                    break
            for table in page.extract_tables() or []:
                for cells in table:
                    cleaned = [(c or "").strip() for c in cells]
                    if not cleaned or not cleaned[0].isdigit():
                        continue
                    item_no = cleaned[0]
                    # Name is the first non-empty cell after the STT column.
                    name = next(
                        (c for c in cleaned[1:] if c and not _looks_like_meaning(c)),
                        "",
                    )
                    if not name:
                        continue
                    normalized = normalize_typography(name)
                    core, _ = split_parenthetical(normalized)
                    canonical_name = core or normalized
                    key = canonical_key_for(canonical_name)
                    if not key:
                        continue
                    category = classify_category(canonical_name, specimen)
                    rows.append(
                        CatalogRow(
                            source_pdf="lab_list_pdf",
                            source_page=page_index + 1,
                            source_item=item_no,
                            raw_name=normalized,
                            normalized_name=core,
                            canonical_key=key,
                            canonical_name=canonical_name,
                            category=category,
                            specimen=specimen,
                            local_name=normalized,
                        )
                    )
    return rows


def _looks_like_meaning(text: str) -> bool:
    """Heuristic: the 'Ý nghĩa' column is long prose, not a test name."""
    return len(text) > 45 or text.count(" ") > 6


# ---------------------------------------------------------------------------
# Stage 1c: merge/dedupe into the combined catalog
# ---------------------------------------------------------------------------

# Known equivalence rules that fold two canonical keys into one.
KEY_EQUIVALENCE = {
    "ure": "ure",
    "ure_mau": "ure",
    "ure_nieu": "ure",
    "creatinin": "creatinine",
    "creatinine": "creatinine",
    "creatinin_mau": "creatinine",
    "creatinin_nieu": "creatinine",
    "calci": "calci",
    "canxi": "calci",
    "calci_toan_phan": "calci",
    "canci_ion_hoa_bang_dien_cuc_chon_loc": "calci_ion_hoa",
    "calci_ion_hoa": "calci_ion_hoa",
    "canxi_ion_hoa": "calci_ion_hoa",
    "glucose_mau": "glucose",
    "acid_uric_mau": "acid_uric",
    "axit_uric": "acid_uric",
    "acid_uric": "acid_uric",
    "feritin": "ferritin",
    "ferritin": "ferritin",
    "ck_mb_mass": "ck_mb",
    "ck_mb": "ck_mb",
    "cpk": "ck",
    "ck": "ck",
    "crphs": "crp_hs",
    "crp_hs": "crp_hs",
    "proteid_mau": "protein_toan_phan",
    "protein_toan_phan": "protein_toan_phan",
    "hba1c": "hba1c",
}


def resolve_key(key: str) -> str:
    """Fold a raw canonical key onto its equivalence-class key."""
    return KEY_EQUIVALENCE.get(key, key)


def merge_catalog(rows: Sequence[CatalogRow]) -> List[CatalogRow]:
    """Merge ministry + local rows by resolved canonical key.

    Ministry rows are preferred for canonical naming; local names are kept as
    ``local_name`` and provenance from both PDFs is preserved in ``notes``.
    """
    by_key: Dict[str, CatalogRow] = {}
    for row in rows:
        row.canonical_key = resolve_key(row.canonical_key)
        existing = by_key.get(row.canonical_key)
        if existing is None:
            by_key[row.canonical_key] = row
            continue
        # Prefer ministry as canonical carrier.
        ministry = existing if existing.source_pdf.startswith("lab_med") else row
        local = row if ministry is existing else existing
        merged = CatalogRow(
            source_pdf="both" if ministry.source_pdf != local.source_pdf else ministry.source_pdf,
            source_page=ministry.source_page,
            source_item=ministry.source_item,
            raw_name=ministry.raw_name,
            normalized_name=ministry.normalized_name,
            canonical_key=row.canonical_key,
            canonical_name=ministry.canonical_name,
            category=ministry.category if ministry.category != "chemistry" else local.category,
            specimen=ministry.specimen if ministry.specimen != "unknown" else local.specimen,
            official_name=ministry.official_name or existing.official_name,
            local_name=local.local_name or ministry.local_name,
            notes="; ".join(
                sorted({
                    f"{existing.source_pdf}#{existing.source_page}:{existing.source_item}",
                    f"{row.source_pdf}#{row.source_page}:{row.source_item}",
                })
            ),
        )
        by_key[row.canonical_key] = merged
    return sorted(by_key.values(), key=lambda r: (r.specimen, r.canonical_key))



# ---------------------------------------------------------------------------
# Stage 2: derive aliases from the combined PDF catalog (before abbreviation.txt)
# ---------------------------------------------------------------------------

# Generic words that must never become standalone aliases.
GENERIC_STOPWORDS = {
    "máu", "mau", "dịch", "dich", "test", "định lượng", "dinh luong",
    "nước tiểu", "nuoc tieu", "các chất điện giải", "cac chat dien giai",
    "niệu", "nieu", "toàn phần", "toan phan",
}

# Minimal acceptable alias length after normalization (chars), unless whitelisted.
MIN_ALIAS_LEN = 2


def _alias_priority(source: str) -> int:
    return {
        "manual_curation": 5,
        "current_seed": 4,
        "combined_lab_catalog": 3,
        "abbreviation_txt_alias": 2,
    }.get(source, 1)


def _is_context_required(term: str) -> bool:
    key = _strip_accents(term.lower()).strip()
    return key in CONTEXT_REQUIRED


def _acceptable_alias(term: str) -> bool:
    stripped = term.strip()
    if not stripped:
        return False
    low = stripped.lower()
    if low in GENERIC_STOPWORDS or _strip_accents(low) in {
        _strip_accents(w) for w in GENERIC_STOPWORDS
    }:
        return False
    # allow single-letter context-required electrolytes, else require length >= 2
    if len(_strip_accents(low)) < MIN_ALIAS_LEN and low not in CONTEXT_REQUIRED:
        return False
    # reject pure numbers / prose fragments
    if re.fullmatch(r"[\d\s.,;:%()-]+", stripped):
        return False
    return True


def derive_pdf_aliases(catalog: Sequence[CatalogRow]) -> List[AliasRow]:
    """Generate alias rows from the combined catalog.

    Sources of aliases per catalog row:

    * canonical/official/local concise names (prefix already stripped);
    * parenthetical aliases inside raw names;
    * orthographic/spelling variants.
    """
    aliases: List[AliasRow] = []
    seen: set[Tuple[str, str]] = set()  # (normalized term, canonical_key)

    def emit(term: str, row: CatalogRow, note: str) -> None:
        term = normalize_typography(term)
        if not _acceptable_alias(term):
            return
        norm = _strip_accents(term.lower())
        dedupe_key = (norm, row.canonical_key)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        aliases.append(
            AliasRow(
                term=term,
                canonical_key=row.canonical_key,
                canonical_name=row.canonical_name,
                source="combined_lab_catalog",
                source_detail=f"{row.source_pdf}#{row.source_page}:{row.source_item}",
                category=row.category,
                specimen=row.specimen,
                requires_context=_is_context_required(term),
                priority=_alias_priority("combined_lab_catalog"),
                notes=note,
            )
        )

    for row in catalog:
        core_names = {row.canonical_name, row.normalized_name}
        if row.local_name:
            core_names.add(split_parenthetical(row.local_name)[0])
        # parenthetical aliases from raw name
        _, paren_aliases = split_parenthetical(row.raw_name)
        for frag in paren_aliases:
            # keep short abbreviations and drop long descriptive glosses
            if len(frag) <= 24:
                core_names.add(frag)
        for name in list(core_names):
            if not name:
                continue
            emit(name, row, "pdf_core_or_paren_alias")
            for variant in orthographic_variants(name):
                emit(variant, row, "orthographic_variant")

    return aliases


# ---------------------------------------------------------------------------
# Stage 3: supplemental aliases from abbreviation.txt
# ---------------------------------------------------------------------------

_ABBREV_LINE_RE = re.compile(r"^\s*(\S+(?:\s*-\s*\S+)?)\s+(.*\S)\s*$")


def parse_abbreviation_file() -> List[Tuple[str, str]]:
    """Return ``(abbr, gloss)`` pairs from abbreviation.txt."""
    pairs: List[Tuple[str, str]] = []
    if not ABBREVIATION_TXT.exists():
        return pairs
    for line in ABBREVIATION_TXT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = _ABBREV_LINE_RE.match(line)
        if not m:
            continue
        abbr, gloss = m.group(1).strip(), m.group(2).strip()
        pairs.append((abbr, gloss))
    return pairs


def supplemental_abbrev_aliases(
    catalog: Sequence[CatalogRow],
    existing_aliases: Sequence[AliasRow],
) -> Tuple[List[AliasRow], List[dict]]:
    """Add abbreviation.txt aliases only when they add a missing lab alias.

    Returns (accepted alias rows, link/audit records for the trace CSV).
    """
    catalog_by_key = {row.canonical_key: row for row in catalog}
    existing_norm = {_strip_accents(a.term.lower()) for a in existing_aliases}

    new_aliases: List[AliasRow] = []
    links: List[dict] = []

    for abbr, gloss in parse_abbreviation_file():
        low = abbr.lower().strip()
        norm_low = _strip_accents(low)
        decision = ""
        canonical_key = ""

        if norm_low in ABBREV_UNIT_BLOCKLIST or low in ABBREV_UNIT_BLOCKLIST:
            decision = "reject_unit"
        elif norm_low in {_strip_accents(x) for x in ABBREV_BLOCKLIST} or low in ABBREV_BLOCKLIST:
            decision = "reject_non_lab"
        else:
            canonical_key = ABBREV_CANONICAL_LINKS.get(low, "")
            if not canonical_key:
                cand = canonical_key_for(gloss)
                if cand in catalog_by_key:
                    canonical_key = cand
            if not canonical_key or canonical_key not in catalog_by_key:
                decision = "defer_guideline_check"
            else:
                decision = "accept"

        links.append({
            "abbr": abbr,
            "gloss": gloss,
            "canonical_key": canonical_key,
            "decision": decision,
        })

        if decision != "accept":
            continue

        row = catalog_by_key[canonical_key]
        surfaces = ABBREV_EXTRA_ALIASES.get(low, [abbr])
        for surface in surfaces:
            norm_surface = _strip_accents(surface.lower())
            if norm_surface in existing_norm:
                continue
            if not _acceptable_alias(surface):
                continue
            existing_norm.add(norm_surface)
            new_aliases.append(
                AliasRow(
                    term=surface,
                    canonical_key=row.canonical_key,
                    canonical_name=row.canonical_name,
                    source="abbreviation_txt_alias",
                    source_detail=f"abbreviation.txt:{abbr}",
                    category=row.category,
                    specimen=row.specimen,
                    requires_context=_is_context_required(surface),
                    priority=_alias_priority("abbreviation_txt_alias"),
                    notes=f"gloss={gloss}",
                )
            )
    return new_aliases, links



# ---------------------------------------------------------------------------
# Current seed carry-over + canonical map + CSV writers
# ---------------------------------------------------------------------------

# Map current flat seeds to canonical keys where a PDF concept exists.
CURRENT_SEED_LINKS = {
    "wbc": ("bach_cau", "Bạch cầu", "hematology", "blood"),
    "rbc": ("hong_cau", "Hồng cầu", "hematology", "blood"),
    "hgb": ("hemoglobin", "Hemoglobin", "hematology", "blood"),
    "hct": ("hematocrit", "Hematocrit", "hematology", "blood"),
    "plt": ("tieu_cau", "Tiểu cầu", "hematology", "blood"),
    "neut%": ("neutrophil", "Neutrophil %", "hematology", "blood"),
    "lymph%": ("lymphocyte", "Lymphocyte %", "hematology", "blood"),
    "lyph%": ("lymphocyte", "Lymphocyte %", "hematology", "blood"),
    "glucose": ("glucose", "Glucose", "chemistry", "blood"),
    "creatinine": ("creatinine", "Creatinin", "chemistry", "blood"),
    "bun": ("ure", "Urê", "chemistry", "blood"),
    "ast": ("ast", "AST", "chemistry", "blood"),
    "alt": ("alt", "ALT", "chemistry", "blood"),
    "bilirubin": ("bilirubin_toan_phan", "Bilirubin toàn phần", "chemistry", "blood"),
    "troponin": ("troponin_t", "Troponin T", "chemistry", "blood"),
    "inr": ("inr", "INR", "coagulation", "blood"),
    "crp": ("crp", "CRP", "immunology", "blood"),
    "lactate": ("lactat", "Lactat", "chemistry", "blood"),
    "ua": ("tong_phan_tich_nuoc_tieu", "Tổng phân tích nước tiểu", "urinalysis", "urine"),
    "cbc": ("cong_thuc_mau", "Công thức máu", "hematology", "blood"),
    "công thức máu": ("cong_thuc_mau", "Công thức máu", "hematology", "blood"),
    "xét nghiệm chức năng gan": ("chuc_nang_gan", "Xét nghiệm chức năng gan", "chemistry", "blood"),
    "bạch cầu": ("bach_cau", "Bạch cầu", "hematology", "blood"),
    "kali": ("kali", "Kali", "chemistry", "blood"),
    "cea": ("cea", "CEA", "tumor_marker", "blood"),
    "huyết khối": ("huyet_khoi", "Huyết khối", "coagulation", "blood"),
    "k": ("kali", "Kali", "chemistry", "blood"),
}

CURRENT_SEED_TERMS = [
    "WBC", "RBC", "HGB", "HCT", "PLT", "NEUT%", "LYMPH%", "LYPH%", "glucose",
    "creatinine", "BUN", "AST", "ALT", "bilirubin", "troponin", "INR", "CRP",
    "lactate", "UA", "CBC", "công thức máu", "xét nghiệm chức năng gan",
    "bạch cầu", "kali", "cea", "huyết khối", "k",
]


def current_seed_aliases(existing: Sequence[AliasRow]) -> List[AliasRow]:
    """Carry over the current flat seed terms as high-priority aliases."""
    existing_pairs = {(_strip_accents(a.term.lower()), a.canonical_key) for a in existing}
    rows: List[AliasRow] = []
    for term in CURRENT_SEED_TERMS:
        low = term.lower()
        key, cname, cat, spec = CURRENT_SEED_LINKS.get(
            low, (canonical_key_for(term), term, "chemistry", "blood")
        )
        norm = _strip_accents(low)
        if (norm, key) in existing_pairs:
            continue
        existing_pairs.add((norm, key))
        rows.append(
            AliasRow(
                term=term,
                canonical_key=key,
                canonical_name=cname,
                source="current_seed",
                source_detail="lab_seed_terms.csv",
                category=cat,
                specimen=spec,
                requires_context=_is_context_required(term),
                priority=_alias_priority("current_seed"),
                notes="carried_from_current_seed",
            )
        )
    return rows


def build_canonical_map(aliases: Sequence[AliasRow]) -> List[dict]:
    """Group aliases by canonical_key into the canonical map rows."""
    grouped: Dict[str, dict] = {}
    for a in aliases:
        entry = grouped.setdefault(a.canonical_key, {
            "canonical_key": a.canonical_key,
            "canonical_name": a.canonical_name,
            "category": a.category,
            "default_specimen": a.specimen,
            "aliases": [],
            "external_source_notes": set(),
        })
        if a.term not in entry["aliases"]:
            entry["aliases"].append(a.term)
        entry["external_source_notes"].add(a.source_detail)
    rows: List[dict] = []
    for key in sorted(grouped):
        e = grouped[key]
        rows.append({
            "canonical_key": e["canonical_key"],
            "canonical_name": e["canonical_name"],
            "category": e["category"],
            "default_specimen": e["default_specimen"],
            "aliases": "|".join(e["aliases"]),
            "external_source_notes": "; ".join(sorted(e["external_source_notes"])),
        })
    return rows


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

# ---------------------------------------------------------------------------
# Manual curation concepts (plan section 9)
#
# The hematology/coagulation/electrolyte/blood-gas concepts below are common in
# Vietnamese notes but are NOT in the ministry biochemistry list, and the
# hospital-catalog hematology pages do not extract cleanly as tables. The plan
# authorizes a curated manual slice for exactly these concepts so they exist as
# canonical concepts and so deferred abbreviations (Hb, Hct, MCH, PT, ESR, ...)
# can link to a real canonical key instead of being dropped.
#
# Each entry: (canonical_key, canonical_name, category, specimen, [alias surfaces])
# ---------------------------------------------------------------------------

MANUAL_CONCEPTS: Tuple[Tuple[str, str, str, str, List[str]], ...] = (
    ("hemoglobin", "Hemoglobin", "hematology", "blood", ["hemoglobin", "Hb", "HGB"]),
    ("hematocrit", "Hematocrit", "hematology", "blood", ["hematocrit", "Hct", "HCT"]),
    ("mch", "MCH", "hematology", "blood", ["MCH"]),
    ("mchc", "MCHC", "hematology", "blood", ["MCHC"]),
    ("mcv", "MCV", "hematology", "blood", ["MCV"]),
    ("mau_lang", "Máu lắng", "hematology", "blood",
     ["máu lắng", "tốc độ máu lắng", "ESR"]),
    ("huyet_do", "Huyết đồ", "hematology", "blood", ["huyết đồ"]),
    ("pmn", "Bạch cầu đa nhân", "hematology", "blood", ["PMN", "bạch cầu đa nhân"]),
    ("aptt", "APTT", "coagulation", "blood", ["APTT", "aPTT", "PTT"]),
    ("pt", "PT (thời gian prothrombin)", "coagulation", "blood",
     ["PT", "thời gian prothrombin"]),
    ("tt", "TT (thời gian thrombin)", "coagulation", "blood", ["TT"]),
    ("fibrinogen", "Fibrinogen", "coagulation", "blood", ["fibrinogen"]),
    ("natri", "Natri", "chemistry", "blood", ["natri", "Na"]),
    ("bicarbonate", "Bicarbonate", "blood_gas", "blood", ["bicarbonate", "HCO3"]),
    ("co2", "CO2", "blood_gas", "blood", ["CO2"]),
    ("sao2", "SaO2", "blood_gas", "blood", ["SaO2"]),
    ("ph", "pH", "blood_gas", "blood", ["pH"]),
    ("magie", "Magiê", "chemistry", "blood", ["magie", "magiê", "Mg"]),
)


def manual_catalog_rows() -> List[CatalogRow]:
    """Return catalog rows for manually curated concepts (plan section 9)."""
    rows: List[CatalogRow] = []
    for key, name, category, specimen, _aliases in MANUAL_CONCEPTS:
        rows.append(
            CatalogRow(
                source_pdf="manual_curation",
                source_page=0,
                source_item="",
                raw_name=name,
                normalized_name=name,
                canonical_key=key,
                canonical_name=name,
                category=category,
                specimen=specimen,
                notes="manual_curation (plan section 9)",
            )
        )
    return rows


def manual_aliases() -> List[AliasRow]:
    """Emit high-priority alias rows for manually curated concept surfaces."""
    rows: List[AliasRow] = []
    for key, name, category, specimen, aliases in MANUAL_CONCEPTS:
        for surface in aliases:
            if not _acceptable_alias(surface):
                continue
            rows.append(
                AliasRow(
                    term=surface,
                    canonical_key=key,
                    canonical_name=name,
                    source="manual_curation",
                    source_detail="plan_section_9",
                    category=category,
                    specimen=specimen,
                    requires_context=_is_context_required(surface),
                    priority=_alias_priority("manual_curation"),
                    notes="manual_curation",
                )
            )
    return rows




# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _alias_to_dict(a: AliasRow) -> dict:
    return {
        "term": a.term,
        "canonical_key": a.canonical_key,
        "canonical_name": a.canonical_name,
        "source": a.source,
        "source_detail": a.source_detail,
        "category": a.category,
        "specimen": a.specimen,
        "requires_context": "true" if a.requires_context else "false",
        "priority": a.priority,
        "notes": a.notes,
    }


ALIAS_FIELDS = (
    "term", "canonical_key", "canonical_name", "source", "source_detail",
    "category", "specimen", "requires_context", "priority", "notes",
)
CATALOG_FIELDS = (
    "source_pdf", "source_page", "source_item", "raw_name", "normalized_name",
    "canonical_key", "canonical_name", "category", "specimen",
    "official_name", "local_name", "notes",
)


def _dedupe_final(aliases: Sequence[AliasRow]) -> List[AliasRow]:
    """Keep one alias per (normalized term, canonical_key); higher priority wins."""
    best: Dict[Tuple[str, str], AliasRow] = {}
    for a in aliases:
        key = (_strip_accents(a.term.lower()), a.canonical_key)
        prev = best.get(key)
        if prev is None or a.priority > prev.priority:
            best[key] = a
    return sorted(best.values(), key=lambda a: (-a.priority, a.canonical_key, a.term))


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Stage 1: combined PDF catalog ------------------------------------
    ministry_rows = extract_ministry_rows()
    local_rows = extract_lab_list_rows()
    manual_rows = manual_catalog_rows()
    catalog = merge_catalog([*ministry_rows, *local_rows, *manual_rows])
    _write_csv(
        GENERATED_DIR / "combined_lab_catalog.csv",
        CATALOG_FIELDS,
        [row.__dict__ for row in catalog],
    )

    # ---- Stage 2: PDF-derived aliases (first) -----------------------------
    pdf_aliases = derive_pdf_aliases(catalog)
    _write_csv(
        GENERATED_DIR / "pdf_alias_links.csv",
        ALIAS_FIELDS,
        [_alias_to_dict(a) for a in pdf_aliases],
    )

    # ---- Stage 3: abbreviation.txt supplemental aliases (after PDFs) ------
    abbrev_aliases, abbrev_links = supplemental_abbrev_aliases(catalog, pdf_aliases)
    _write_csv(
        GENERATED_DIR / "abbreviation_alias_links.csv",
        ("abbr", "gloss", "canonical_key", "decision"),
        abbrev_links,
    )

    # ---- current seed carry-over ------------------------------------------
    seed_aliases = current_seed_aliases([*pdf_aliases, *abbrev_aliases])

    # ---- manual curation aliases (plan section 9) ---------------------------
    manual_aliases_list = manual_aliases()

    # ---- combine + dedupe candidates --------------------------------------
    all_aliases = [*seed_aliases, *manual_aliases_list, *pdf_aliases, *abbrev_aliases]
    curated = _dedupe_final(all_aliases)

    _write_csv(
        GENERATED_DIR / "lab_terms_candidates.csv",
        ALIAS_FIELDS,
        [_alias_to_dict(a) for a in curated],
    )

    # rejected trace (units + non-lab from abbreviation.txt)
    rejected = [
        {"term": r["abbr"], "gloss": r["gloss"], "decision": r["decision"]}
        for r in abbrev_links
        if r["decision"] in {"reject_unit", "reject_non_lab", "defer_guideline_check"}
    ]
    _write_csv(
        GENERATED_DIR / "lab_terms_rejected.csv",
        ("term", "gloss", "decision"),
        rejected,
    )

    # ---- final parser-facing resources ------------------------------------
    _write_csv(
        DATA_DIR / "lab_terms_curated.csv",
        ALIAS_FIELDS,
        [_alias_to_dict(a) for a in curated],
    )
    canonical_map = build_canonical_map(curated)
    _write_csv(
        DATA_DIR / "lab_canonical_map.csv",
        ("canonical_key", "canonical_name", "category", "default_specimen",
         "aliases", "external_source_notes"),
        canonical_map,
    )

    accepted_abbr = sum(1 for r in abbrev_links if r["decision"] == "accept")
    print("=" * 70)
    print("Lab resource build complete")
    print("=" * 70)
    print(f"Ministry catalog rows : {len(ministry_rows)}")
    print(f"Local catalog rows    : {len(local_rows)}")
    print(f"Combined catalog keys : {len(catalog)}")
    print(f"PDF-derived aliases   : {len(pdf_aliases)}")
    print(f"Abbrev accepted/total : {accepted_abbr}/{len(abbrev_links)}")
    print(f"Current seed aliases  : {len(seed_aliases)}")
    print(f"Curated aliases (final): {len(curated)}")
    print(f"Canonical concepts     : {len(canonical_map)}")


if __name__ == "__main__":
    main()

