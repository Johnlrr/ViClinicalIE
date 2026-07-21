# NER-0 / NER-1 Implementation

## NER-0

- Freeze V1 twice with `scripts/freeze_v1_baseline.py`.
- Validate predictions with `scripts/run_validate.py`.
- Run diagnostic evaluation with `scripts/run_evaluate.py`.
- Run the documented non-official scorer with
  `scripts/run_official_like_score.py`.
- Run span/type ceilings with `scripts/run_ner_oracles.py`.
- The shared annotation/data contracts are
  `data/golden/ANNOTATION_GUIDELINE_V2.md` and
  `data/golden/ner_data_schema.json`.
- Validate data-owner pilots with `scripts/validate_ner_dataset.py`.

## NER-1 provisioning

Use a dedicated Python 3.10/3.11 environment for release builds. The current
development environment can be checked with:

```powershell
python -m pip install -r requirements-v2-ner.txt
python scripts/check_gliner_environment.py
python scripts/provision_gliner.py --model urchade/gliner_multi-v2.1 --max-workers 1
python scripts/provision_gliner.py --model microsoft/mdeberta-v3-base --max-workers 1 --tokenizer-only
```

The pinned revisions are stored in `configs/gliner_zero_shot.yaml`. Both the
GLiNER checkpoint and the transitive mDeBERTa tokenizer must be present for
offline inference.

## Offline smoke and benchmark

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python scripts/run_gliner_smoke.py
python scripts/benchmark_gliner.py --split development
```

`benchmark_gliner.py` uses `ClinicalIEPipeline(..., ner_only=True)`, writes
submission-safe JSON separately from internal provenance, validates raw offsets,
and produces exact/relaxed per-type reports. Threshold `0.35` is a reproduction
point only; calibration belongs to NER-2.

## Test

```powershell
python -m pytest -q
python -m compileall -q src scripts tests
git diff --check
```