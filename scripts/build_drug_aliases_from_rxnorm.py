"""Build an expanded drug_aliases.csv from RXNCONSO.RRF RxNorm atoms.

Strategy:
- Keep all existing curated terms from the current drug_aliases.csv (high-precision).
- Extract RxNorm IN/PIN/MIN/BN atoms (SAB=RXNORM), filter to clean clinical drug names.
- Append them below the curated section, sorted alphabetically.
- The parser treats all entries in drug_aliases.csv as ``drug_dictionary`` seeds
  with confidence 1.0, so this makes RxNorm the primary name source.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.normalization import normalize_for_matching

# ── RxNorm entry extraction ─────────────────────────────────────────────────

RRF_PATH = ROOT / "data_resources" / "RXNCONSO.RRF"
OUTPUT_PATH = ROOT / "data_resources" / "drug_aliases.csv"

# TTY values that represent named clinical drug concepts.
PREFERRED_TTY = frozenset({"IN", "PIN", "MIN", "BN"})

# Tokens/substrings that strongly suggest a non-drug or overly broad chemical entry.
_NON_DRUG_PATTERNS = re.compile(
    r"\b(?:"
    r"extract|oil|wax|pollen|vaccine|vaccinia|"
    r"bark|flower|wood|seed|fruit|leaf|root|whole|"
    r"acetate|chloride|sulfate|hydrochloride|mesylate|maleate|"
    r"butyl|methyl|ethyl|propyl|decyl|octyl|nonyl|"
    r"glycol|glycerol|phospholipid|phosphatidyl|"
    r"copolymer|polymer|resin|emulsion|"
    r"allergen|allergenic|antigen|"
    r"bacteria|bacterial|virus|viral|yeast|fungal|"
    r"perfume|fragrance|cosmetic|shampoo|soap|"
    r"diagnostic|reagent|stain|medium"
    r")\b",
    re.IGNORECASE,
)

# Biochemical/lab analytes that are RxNorm ingredients but in Vietnamese clinical
# notes are almost always lab test names, not drug mentions. Exclude to reduce
# false positives in sections like LAB_RESULT_SECTION.
_LAB_ANALYTE_EXCLUDE: frozenset[str] = frozenset({
    normalize_for_matching(t).strip().lower()
    for t in [
        "creatinine",
        "cholesterol",
        "alanine",
        "aspartate",
        "beta-alanine",
        "bilirubin",
        "albumin",
        "glucose",
        "sodium",
        "potassium",
        "calcium",
        "magnesium",
        "chloride",
        "phosphate",
        "urea",
        "urate",
        "uric acid",
        "lactate",
        "pyruvate",
        "citrate",
        "triglyceride",
        "hdl cholesterol",
        "ldl cholesterol",
        "c reactive protein",
        "caffeine",
    ]
})

# Minimum word count for a name to be useful (shorter terms like "senna" are fine).
# Maximum word count — skip over-long combination strings.
_MIN_WORDS = 1
_MAX_WORDS = 5

# Minimum character length for a single word.
_MIN_CHARS = 2


def _is_clean_drug_name(name: str) -> bool:
    """Heuristic filter to keep only plausible clinical drug names."""
    if not name or not name.strip():
        return False
    # Must start with a letter.
    if not re.match(r"[a-zA-ZÀ-ỹ]", name):
        return False
    # Skip if it contains low-value markers.
    if _NON_DRUG_PATTERNS.search(name):
        return False
    # Skip strings with too many "/" — multi-component combinations.
    if name.count("/") > 4:
        return False
    # Exclude lab analytes that are RxNorm ingredients but appear as lab values.
    if normalize_for_matching(name).strip().lower() in _LAB_ANALYTE_EXCLUDE:
        return False
    # Measure word count on a simplified view.
    cleaned = name.replace("/", " ").replace("-", " ").replace(",", " ")
    words = cleaned.split()
    if len(words) < _MIN_WORDS or len(words) > _MAX_WORDS:
        return False
    if any(len(w) < _MIN_CHARS for w in words if w.strip("()")):
        return False
    return True


def extract_rxnorm_seeds(rrf_path: str | Path) -> list[str]:
    """Extract unique drug name strings from RXNCONSO.RRF.

    Keeps only RXNORM SAB atoms with TTY in {IN, PIN, MIN, BN}
    that pass the clean-drug-name heuristic.
    """
    rrf_path = Path(rrf_path)
    seen: set[str] = set()
    names: list[str] = []

    with rrf_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            fields = line.rstrip("\n\r").split("|")
            if len(fields) < 17:
                continue
            suppress = fields[16].strip()
            if suppress != "N":
                continue
            sab = fields[11].strip()
            if sab != "RXNORM":
                continue
            tty = fields[12].strip()
            if tty not in PREFERRED_TTY:
                continue
            name = fields[14].strip()
            if not name:
                continue
            if not _is_clean_drug_name(name):
                continue
            key = name.lower()
            if key not in seen:
                seen.add(key)
                names.append(name)

    names.sort(key=str.casefold)
    return names


# ── Merge with existing curated aliases ─────────────────────────────────────

def load_existing_aliases(path: str | Path) -> list[str]:
    """Load existing drug_aliases.csv, skip header, keep order."""
    path = Path(path)
    if not path.exists():
        return []
    terms: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            term = line.strip()
            if not term or term == "term":
                continue
            key = term.lower().strip()
            if key and key not in seen:
                seen.add(key)
                terms.append(term)
    return terms


# Hard‑coded base curated aliases that RxNorm either doesn't carry as
# IN / PIN / MIN / BN, or carries them only in a qualified form (e.g.
# "insulin, regular, human") that won't match the short alias used in
# Vietnamese notes.
_CURATED_BASE: list[str] = [
    "metoprolol",
    "aspirin",
    "atenolol",
    "atenolol trong",
    "doxycycline",
    "omeprazole",
    "coumadin",
    "warfarin",
    "acetaminophen",
    "tylenol",
    "ibuprofen",
    "advil",
    "levofloxacin",
    "vancomycin",
    "morphine",
    "insulin",
    "furosemide",
    "bumetanide",
    "carvedilol",
    "rosuvastatin",
    "bactrim",
    "pravastatin",
    "clonazepam",
    "nystatin",
    "guaifenesin",
    "amlodipine",
    "senna",
    "docusate sodium",
]


def build_merged_aliases(
    existing_path: str | Path,
    rxnorm_names: list[str],
) -> list[str]:
    """Merge curated base aliases with new RxNorm names, preserving order.

    Curated aliases come first (they have manual priority for edge cases),
    then new RxNorm terms that aren't already present.
    """
    seen: set[str] = set()
    merged: list[str] = []

    for term in _CURATED_BASE:
        key = term.lower().strip()
        if key not in seen:
            seen.add(key)
            merged.append(term)

    for name in rxnorm_names:
        key = name.lower().strip()
        if key not in seen:
            seen.add(key)
            merged.append(name)
    return merged


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Reading RxNorm catalog from: {RRF_PATH}")
    rxnorm_names = extract_rxnorm_seeds(RRF_PATH)
    print(f"  Extracted {len(rxnorm_names):,} clean drug names from RxNorm IN/PIN/MIN/BN")

    existing = load_existing_aliases(OUTPUT_PATH)
    print(f"  Existing curated aliases: {len(existing):,}")

    merged = build_merged_aliases(OUTPUT_PATH, rxnorm_names)
    print(f"  Total merged aliases: {len(merged):,}")

    # Write output.
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        fh.write("term\n")
        for term in merged:
            fh.write(f"{term}\n")

    print(f"  Written to: {OUTPUT_PATH.relative_to(ROOT)}")

    # Quick sanity: check a few known drugs are present.
    expected = {"amlodipine", "aspirin", "metoprolol", "warfarin", "insulin", "morphine"}
    all_lower = {t.lower().strip() for t in merged}
    missing = {e for e in expected if e not in all_lower}
    if missing:
        print(f"  ⚠ Missing expected drugs: {missing}")
    else:
        print("  ✓ All expected drugs present")


if __name__ == "__main__":
    main()
