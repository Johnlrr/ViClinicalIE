# ViClinicalIE

Foundation for the Viettel AI Race clinical text entity extraction and normalization system.

Phase 0 sets up the project skeleton, canonical data layout, config loading, basic logging, and setup smoke tests. It does not implement extraction, linking, inference, or evaluation logic yet.

## Setup

```bash
pip install -r requirements.txt
```

Optional ML dependencies for later NER and dense retrieval phases:

```bash
pip install -r requirements-ml.txt
```

## Phase 0 Smoke Checks

Validate the canonical data layout and golden offsets:

```bash
python scripts/check_setup.py --config configs/default.yaml
```

Run tests:

```bash
python -m pytest
```

## Canonical Data Layout

- `data/raw/input/`: public input files `1.txt` through `100.txt`.
- `data/golden/input/`: copied raw input files for the 20 golden examples.
- `data/golden/gold/`: golden annotations for IDs `1` through `20`.
- `data/terminologies/icd10_byt.csv`: ICD-10 source table.
- `data/terminologies/RXNCONSO.RRF`: RxNorm source table.

Root-level source files are intentionally left in place.

