# NER-3 V1 Expert Integration

NER-3 integrates the frozen NER-2 GLiNER configuration with the existing V1
expert extractors while keeping `SpanCandidate` and submission JSON unchanged.
It is a development-only diagnostic milestone. It does **not** select or promote
a production fusion policy automatically.

## Approved checkpoints

`configs/ner3/experiment_matrix.yaml` freezes the comparison order:

| Checkpoint | Mode | Meaning |
|---|---|---|
| A | `v1` | V1 expert sources only (`V1_FROZEN` comparison) |
| B | `gliner` | frozen selected NER-2 GLiNER only |
| C | `naive_union` | exact-deduplicated V1 + GLiNER diagnostic union |
| D | `simple_fusion` | GLiNER-centered deterministic fusion with narrow structured anchors |

C is diagnostic-only. D keeps GLiNER-only hypotheses; expert confirmation is
not a requirement. Structured anchors can replace a contained GLiNER boundary
only for same-type drug/lab/result/imaging evidence. Near overlaps are otherwise
not silently merged.

## Reproducible candidate ledger

The runner loads `configs/ner3/base.yaml`, enables the frozen GLiNER source and
all V1 expert sources, and calls the main `ClinicalIEPipeline` candidate API
once per note. It normalizes evidence and writes a raw-offset/hash-validated
ledger. All four checkpoints replay these same ledger bytes; their manifests
must contain the same ledger-manifest hash.

This separates model inference from resolver/fusion comparisons and prevents an
A/B/C/D result from being caused by four different model calls.

## Commands (do not run implicitly)

Prepare the local frozen model/tokenizer first and keep Hugging Face offline:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

# Development only. This is the model-bearing command.
python scripts/run_ner3_experiments.py

# Replay an already reviewed ledger without loading a model.
python scripts/run_ner3_experiments.py `
  --ledger-dir outputs/experiments/ner3/candidate_ledgers

python scripts/summarize_ner3_experiments.py
python scripts/review_ner3_source_errors.py
```

The runner rejects calibration and lockbox. Checkpoints requested separately
must satisfy their declared predecessors. Run A/B/C/D in order or run the
default complete plan.

## Artifacts and gates

The runner writes:

- `candidate_ledgers/<id>.json` and `candidate_ledger_manifest.json`;
- `complementarity.json`, including source/type categories and gold utility;
- `A` through `D` prediction/evaluation directories and run manifests.
- separate `predictions/extraction_only` and `predictions/end_to_end` trees;
- official-like end-to-end score, density, runtime, prediction diff, resolved
  config, and source trace artifacts.

The summarizer requires all checkpoints, one shared ledger hash, zero evidence
and validation errors, zero exact final duplicates, and preservation of exact
GLiNER-only hypotheses at checkpoint D. Passing gates means only
`manual_review_required`. It never promotes D.

The source reviewer creates a deterministic queue by checkpoint, source, entity
type, and FP/FN/boundary/type category. Source attribution comes from candidate
ledger/provenance evidence, not guessed text. A human review is required before
any later production or NER-4 decision.

## Targeted tests

```powershell
python -m pytest tests/test_ner3_experiment_runner.py `
  tests/test_ner3_candidate_ledger.py tests/test_ner3_complementarity.py `
  tests/test_ner3_evidence_adapter.py tests/test_ner3_pipeline_trace.py `
  tests/test_ner3_simple_fusion.py -q
python -m py_compile scripts/run_ner3_experiments.py `
  scripts/summarize_ner3_experiments.py scripts/review_ner3_source_errors.py
```

No model benchmark or full development run is part of implementation testing.

## One-note smoke checkpoint

The approved implementation checkpoint uses development note `1`, then replays
the resulting candidate ledger a second time. Passing the smoke proves cache/
ledger mechanics and A/B reproduction only; it cannot select D. The frozen
`configs/ner3/selected_expert_profile.yaml` therefore remains
`pending_full_development` with `selected_system: null` until the 12-note
development gate is explicitly authorized and completed.
