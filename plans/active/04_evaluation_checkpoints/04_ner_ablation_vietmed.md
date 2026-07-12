# Checkpoint 04 — VietMed NER Ablation on Silver Set

Date: 2026-07-12

## Scope

Ablation requested by [`03_checkpoint_vietmed_ner_adapter.md`](03_checkpoint_vietmed_ner_adapter.md:145) §6 ("Còn lại cho evaluation sau") and [`plan_ner.md`](../../../plan_ner.md) §7: compare the deterministic parser/rule architecture with `--skip-ner` (baseline) against the same architecture with the VietMed-NER adapter (`--ner-label-map vietmed`) enabled, both scored against the 20-file silver set in [`silver_test/output`](../../../silver_test/output).

## Commands Used

Baseline (no NER):

```bash
python scripts/build_new_arch_outputs.py \
  --only 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20 \
  --outputs-dir outputs/new_arch_demo \
  --analysis-dir analysis/new_arch_demo

python scripts/score_silver.py \
  --pred-dir outputs/new_arch_demo/output \
  --report-md reports/silver_eval_demo.md \
  --report-json reports/silver_eval_demo.json
```

VietMed-NER adapter enabled:

```bash
python scripts/build_new_arch_outputs.py \
  --ner-model 'leduckhai/VietMed-NER::phobert-base-v2-VietMed-NER' \
  --ner-label-map vietmed \
  --ner-device mps \
  --limit 20 \
  --ner-strict \
  --outputs-dir outputs/new_arch_ner_demo \
  --analysis-dir analysis/new_arch_ner_demo

python scripts/score_silver.py \
  --pred-dir outputs/new_arch_ner_demo/output \
  --report-md reports/silver_eval_ner_demo.md \
  --report-json reports/silver_eval_ner_demo.json
```

Both runs used [`scripts/build_new_arch_outputs.py`](../../../scripts/build_new_arch_outputs.py:1) for candidate generation and [`scripts/score_silver.py`](../../../scripts/score_silver.py:1) for ABOUT.md §6 scoring.

## Build Stats Comparison

| Metric | No NER | VietMed-NER |
|---|---:|---:|
| NER candidates | 0 | 844 |
| Raw candidates | 756 | 1378 |
| Merged/linked candidates | 551 | 947 |
| Validation | PASS | PASS |
| Mapping total (mapped/mappable) | 56/116 | 55/246 |
| `THUỐC` coverage | 62.1% | 28.4% |
| `CHẨN_ĐOÁN` coverage | 43.7% | 20.1% |

Raw extraction by type, VietMed-NER run (from [`analysis/new_arch_ner_demo/span_candidates_new_arch_summary.json`](../../../analysis/new_arch_ner_demo/span_candidates_new_arch_summary.json:1)):

| Type | Raw candidates |
|---|---:|
| `TRIỆU_CHỨNG` | 614 |
| `TÊN_XÉT_NGHIỆM` | 292 |
| `CHẨN_ĐOÁN` | 247 |
| `THUỐC` | 82 |
| `KẾT_QUẢ_XÉT_NGHIỆM` | 44 |

`vihealthbert_ner` was the single largest raw source tag (712 of 1378 raw candidates, 615 surviving into the linked/final set) — roughly half of all candidates in this run originated from the NER adapter.

## Silver Score Comparison

| Metric | No NER | VietMed-NER | Delta |
|---|---:|---:|---:|
| text_score | 0.262711 | 0.231964 | −0.030747 |
| assertions_score (J_assertion) | 0.083333 | 0.014560 | −0.068773 |
| candidates_score (J_candidate) | 0.038855 | 0.030230 | −0.008625 |
| final_score | 0.119355 | 0.086049 | −0.033306 |

## Diagnostic Exact-Match Metrics

| Metric | No NER (P/R/F1) | VietMed-NER (P/R/F1) |
|---|---|---|
| span_type | 0.1706 / 0.2541 / 0.2041 | 0.0792 / 0.2027 / 0.1139 |
| full_entity | 0.0998 / 0.1486 / 0.1194 | 0.0465 / 0.1189 / 0.0668 |
| assertions_on_matched_spans | 0.1333 / 0.3636 / 0.1951 | 0.2000 / 0.7500 / 0.3158 |
| candidates_on_matched_spans | 0.1875 / 0.1429 / 0.1622 | 0.1333 / 0.1053 / 0.1176 |

VietMed-NER: TP/FP/FN for span_type = 75/872/295 (vs. no-NER 94/457/276). False positives nearly doubled while true positives dropped, confirming the NER adapter is adding a large volume of low-precision spans rather than recovering missed gold spans.

## Per-Type F1

| Type | No NER | VietMed-NER |
|---|---:|---:|
| `THUỐC` | 0.3333 | 0.1837 |
| `CHẨN_ĐOÁN` | 0.2577 | 0.1255 |
| `TRIỆU_CHỨNG` | 0.2511 | 0.1233 |
| `KẾT_QUẢ_XÉT_NGHIỆM` | 0.0789 | 0.0645 |
| `TÊN_XÉT_NGHIỆM` | 0.0132 | 0.0738 |

`TÊN_XÉT_NGHIỆM` is the only type where the NER adapter improved F1 (0.0132 → 0.0738), consistent with the no-NER baseline's known lab-name weakness noted in [`02_silver_eval_new_arch.md`](02_silver_eval_new_arch.md:51). Every other type regressed.

## Takeaway

Enabling the VietMed-NER adapter (`--ner-label-map vietmed`) made every ABOUT.md official metric (`text_score`, `assertions_score`, `candidates_score`, `final_score`) worse on the 20-file silver scope, and regressed span_type/full_entity F1 for 4 of 5 entity types. The adapter roughly doubled raw candidate volume without a matching recall gain — false positives on span_type nearly doubled (457 → 872) while true positives dropped slightly (94 → 75). This over-generation cascades through merge/linking: `THUỐC`/`CHẨN_ĐOÁN` mapping coverage fell by more than half (62.1%→28.4%, 43.7%→20.1%) simply because there are far more (mostly wrong) mappable spans competing for the same linker.

The one bright spot is `TÊN_XÉT_NGHIỆM`, where NER-sourced candidates add real recall the dictionary/structural pipeline was missing.

## Recommendation

Per [`03_checkpoint_vietmed_ner_adapter.md`](03_checkpoint_vietmed_ner_adapter.md:118) §4.2, the adapter's per-type thresholds (`VIETMED_DEFAULT_THRESHOLDS`) are currently the main lever available without further model changes:

- Consider raising thresholds for `THUỐC`, `CHẨN_ĐOÁN`, and `TRIỆU_CHỨNG` (or disabling NER seeding for these types) since dictionary/rule/parser sources already outperform NER there.
- Consider keeping or lowering the `TÊN_XÉT_NGHIỆM` threshold since NER is the only source showing a net F1 gain for that type.
- Re-run this ablation per type (`--ner-threshold TYPE=value`) before folding VietMed-NER into the default pipeline configuration, and re-check `assertions_score`/`candidates_score` since both are sensitive to the enlarged, noisier candidate pool feeding merge/linking.

## Not Covered

- Full 100-file input set (this ablation used the 20-file silver scope only, matching [`02_silver_eval_new_arch.md`](02_silver_eval_new_arch.md:1)).
- Per-type threshold tuning/sweep for the VietMed adapter.
- Fine-tuning or retraining of the NER backbone; this checkpoint only evaluates the pretrained third-party checkpoint via the adapter.

## Artifacts

- [`reports/silver_eval_demo.md`](../../../reports/silver_eval_demo.md) / `.json` — no-NER baseline score report.
- [`reports/silver_eval_ner_demo.md`](../../../reports/silver_eval_ner_demo.md) / `.json` — VietMed-NER score report.
- [`analysis/new_arch_ner_demo/span_candidates_new_arch_summary.json`](../../../analysis/new_arch_ner_demo/span_candidates_new_arch_summary.json) — raw extraction/source-tag summary for the VietMed-NER run.
- [`outputs/new_arch_demo/output`](../../../outputs/new_arch_demo/output) / [`outputs/new_arch_ner_demo/output`](../../../outputs/new_arch_ner_demo/output) — generated JSON predictions for both runs.
