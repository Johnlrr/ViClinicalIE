# NER-5 — Data Readiness

## Status

Technical implementation and deterministic dataset build are complete. The
bundle intentionally remains `data_ready: false` until a person reviews the
pilot IDs recorded in the manifest and updates `configs/ner5.yaml` with an
approved reviewer/date.

## Retained implementation

```text
configs/ner5.yaml
scripts/build_ner5_data.py
src/ner/task_aligned_generator.py
src/ner/data_validator.py
tests/test_ner5_data.py
data/processed/ner_v2/
```

The one build command creates clean task-aligned data, four deterministic noise
profiles, development/calibration conversions, leakage validation, source audit,
hashes, distributions, pilot review IDs, and the final manifest. Lockbox content
is never exported; only normalized hashes are used for leakage checking.

## Built bundle

| Dataset | Samples | Purpose |
|---|---:|---|
| `task_aligned_train.jsonl` | 147 | Clean construction data and hard negatives |
| `noisy_train.jsonl` | 143 | No-diacritics, missing-space, repeated-token and typo variants |
| `development.jsonl` | 12 | Development-only evaluation view |
| `calibration.jsonl` | 4 | Calibration-only evaluation view |

Training entity distribution covers all five target types:

```text
CHẨN_ĐOÁN: 82
KẾT_QUẢ_XÉT_NGHIỆM: 44
THUỐC: 80
TRIỆU_CHỨNG: 80
TÊN_XÉT_NGHIỆM: 46
```

Technical validation reports zero offset, marker, duplicate, train/evaluation,
near-duplicate, group and lockbox leakage errors. Rebuilding with the same seed
produces byte-identical datasets and manifest.

ViMedNER and VietBioNER are deferred because local license/guideline/partial
annotation evidence is incomplete. `Symptom_and_Disease` remains
`UNMAPPED_REVIEW`. Phase-9 weak data remains `REVIEW` and is excluded.

## Human gate

Review the manifest's `human_review.pilot_sample_ids` for boundary/type,
positive/hard-negative behavior, every noise profile, and ontology surface
plausibility. After an actual review, set `status`, `reviewer`, `date`, and notes
in `configs/ner5.yaml`, then rebuild. Only then may `data_ready` become true and
NER-6 enter its fine-tuning go/no-go decision.

## Commands

```powershell
python -m pytest tests/test_ner5_data.py tests/test_ner_data_validator_v2.py -q
python scripts/build_ner5_data.py
python -m pytest -q
```