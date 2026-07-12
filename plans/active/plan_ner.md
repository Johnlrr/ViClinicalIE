# NER adaptation plan

## Current checkpoint

Notebook `test.ipynb` loads:

- tokenizer: `vinai/phobert-base-v2`
- checkpoint: `leduckhai/VietMed-NER`, subfolder `phobert-base-v2-VietMed-NER`
- task: token classification via `pipeline("ner", aggregation_strategy="simple")`

Checkpoint labels are VietMed-wide, not submission labels:

```text
0: I-ORGAN
1: B-PREVENTIVEMED
2: B-DISEASESYMTOM
3: B-FOODDRINK
4: B-ORGANIZATION
5: B-OCCUPATION
6: B-DRUGCHEMICAL
7: I-FOODDRINK
8: I-DISEASESYMTOM
9: I-UNITCALIBRATOR
10: I-DATETIME
11: I-DIAGNOSTICS
12: B-TRANSPORTATION
13: B-GENDER
14: B-AGE
15: B-DATETIME
16: B-LOCATION
17: B-TREATMENT
18: I-DRUGCHEMICAL
19: I-PREVENTIVEMED
20: I-TREATMENT
21: I-ORGANIZATION
22: 0
23: B-UNITCALIBRATOR
24: B-MEDDEVICETECHNIQUE
25: I-OCCUPATION
26: B-PERSONALCARE
27: I-PERSONALCARE
28: I-GENDER
29: I-SURGERY
30: I-AGE
31: I-LOCATION
32: B-DIAGNOSTICS
33: I-MEDDEVICETECHNIQUE
34: B-ORGAN
35: B-SURGERY
36: I-TRANSPORTATION
```

Our output labels:

- `TRIỆU_CHỨNG`
- `CHẨN_ĐOÁN`
- `THUỐC`
- `TÊN_XÉT_NGHIỆM`
- `KẾT_QUẢ_XÉT_NGHIỆM`

Existing pipeline already expects compact BIO labels in `src/vihealthbert_ner.py`:

```text
O
B/I-TRIỆU_CHỨNG
B/I-CHẨN_ĐOÁN
B/I-THUỐC
B/I-TÊN_XÉT_NGHIỆM
B/I-KẾT_QUẢ_XÉT_NGHIỆM
```

So direct use of VietMed labels will currently decode almost everything as outside, because `_parse_label()` rejects labels not in `TARGET_ENTITY_TYPES`.

## Label mapping hypothesis

Use VietMed model only as semantic seed generator, not final output authority.

Map high-signal labels:

| VietMed label | Submission label | Use |
|---|---|---|
| `DRUGCHEMICAL` | `THUỐC` | seed drug parser |
| `DIAGNOSTICS` | `TÊN_XÉT_NGHIỆM` | seed lab parser |
| `UNITCALIBRATOR` | `KẾT_QUẢ_XÉT_NGHIỆM` | weak seed/result helper only |
| `DISEASESYMTOM` | ambiguous: `CHẨN_ĐOÁN` or `TRIỆU_CHỨNG` | route by section/context |
| `TREATMENT`, `SURGERY`, `PREVENTIVEMED` | usually not target, sometimes treatment/drug context | ignore first; evaluate later |
| others | non-target | ignore |

Ambiguous `DISEASESYMTOM` split rule:

- in diagnosis sections/subsections (`CHRONIC_DISEASES`, `DIAGNOSTIC_FINDINGS`, `HOSPITAL_ASSESSMENT`, etc.) -> `CHẨN_ĐOÁN`
- in symptom/current-history sections (`ADMISSION_REASON`, `CURRENT_SYMPTOMS`, `SYMPTOM_DETAIL`, `CURRENT_HISTORY`) -> `TRIỆU_CHỨNG`
- otherwise keep as low-confidence semantic seed or drop if overlap conflicts with parser/dictionary

## Implementation plan

1. Add label adapter layer.
   - New mapping function converts raw HF labels before `decode_token_predictions()`.
   - Preserve BIO prefix.
   - Convert `0` to `O`.
   - Unknown labels -> `O`.

2. Add context-aware post-map for `DISEASESYMTOM`.
   - Decode raw spans as temporary type, e.g. `DISEASESYMTOM`.
   - Use document line/section overlap to choose `CHẨN_ĐOÁN` vs `TRIỆU_CHỨNG`.
   - If no context, either drop or map by lexical cues; start conservative.

3. Use NER as seeds only.
   - `THUỐC` NER -> `parse_drug_candidates()` expands dose/route/frequency.
   - `TÊN_XÉT_NGHIỆM` NER -> `parse_lab_candidates()` composes lab results.
   - `CHẨN_ĐOÁN`/`TRIỆU_CHỨNG` NER -> merge with dictionary/rules, lower priority than specialized parsers.

4. Add CLI option.
   - Example: `--ner-label-map vietmed`
   - Default stays current compact-label behavior for compatible checkpoints.

5. Calibrate thresholds.
   - Start high:
     - `THUỐC`: 0.75
     - `TÊN_XÉT_NGHIỆM`: 0.70
     - `KẾT_QUẢ_XÉT_NGHIỆM`: 0.80 or disabled initially
     - `CHẨN_ĐOÁN`/`TRIỆU_CHỨNG`: 0.80 due ambiguous source label
   - Tune on `silver_test` using `scripts/score_silver.py`.

6. Add tests.
   - raw `B-DRUGCHEMICAL/I-DRUGCHEMICAL` -> `THUỐC`
   - raw `B-DIAGNOSTICS` -> `TÊN_XÉT_NGHIỆM`
   - raw `B-DISEASESYMTOM` in current symptoms -> `TRIỆU_CHỨNG`
   - raw `B-DISEASESYMTOM` in diagnostic findings -> `CHẨN_ĐOÁN`
   - raw non-target labels drop
   - offset round-trip unchanged

7. Evaluate ablation.
   - baseline: `--skip-ner`
   - current NER without mapping: should add near zero useful spans
   - mapped VietMed NER: compare span/type/full-entity F1, plus FP inspection
   - decide per-type enable/disable by metric gain

## Risk controls

- Do not replace parsers with NER output.
- Keep strict offset validation.
- Drop unknown/non-target VietMed labels.
- Prefer dictionary/parser spans in overlap resolution.
- Treat `DISEASESYMTOM` as high-risk; require section context or high confidence.
- Keep `KẾT_QUẢ_XÉT_NGHIỆM` mostly parser-derived; VietMed units/values likely noisy.

## Expected outcome

Best value likely:

- more drug cores missed by dictionary/RxNorm aliases
- more lab-name seeds for uncommon test names
- modest recall gain for diagnosis/symptom if section routing works

Main danger:

- `DISEASESYMTOM` mixes disease + symptom, causing type swaps
- `DIAGNOSTICS` may include procedures/imaging, not only lab names
- broad medical labels can increase false positives if used directly

Recommended first implementation: adapter + drug/lab-name mapping only. Then evaluate. Add `DISEASESYMTOM` routing only if precision remains acceptable.

## Implementation log

### Status

Steps 1–6 complete. Step 7 (ablation on `silver_test`) pending; not required for code to ship.

### Decision note — conservative DISEASESYMTOM routing

Current version intentionally keeps `DISEASESYMTOM` handling conservative. VietMed `DISEASESYMTOM` spans are decoded as temporary `_DISEASESYMTOM_PENDING` candidates, then routed to `CHẨN_ĐOÁN` or `TRIỆU_CHỨNG` only when section/subsection context is high-confidence enough. Candidates without usable section context are dropped by default via `drop_without_context=True`.

Rationale: first implementation prioritizes precision and avoids type swaps between diagnosis and symptom. This may hurt recall, especially when section parsing fails or mentions appear in unknown sections. Keep this behavior for the first evaluation pass; consider lexical/context fallback later if `silver_test` shows recall loss is too high.

### Code changes

#### `src/vihealthbert_ner.py`

- Added `VIETMED_TO_SUBMISSION` dict: `DRUGCHEMICAL→THUỐC`, `DIAGNOSTICS→TÊN_XÉT_NGHIỆM`, `UNITCALIBRATOR→KẾT_QUẢ_XÉT_NGHIỆM`. Non-target labels map to `O`; literal `0` token maps to `O`.
- Added `_DISEASESYMTOM_PENDING` placeholder + `_TEMP_ENTITY_TYPES` frozenset so the decoder can ingest pending spans before routing.
- Added `map_vietmed_label(label) -> str` — preserves BIOES prefix (`B-` / `I-`), converts `0` to `O`, drops unknown labels to `O`.
- Added `_DIAGNOSIS_SUBSECTIONS`, `_DIAGNOSIS_SECTION_TYPES`, `_SYMPTOM_SUBSECTIONS`, `_SYMPTOM_SECTION_TYPES` frozen sets — mirrored from `src/rule_extractors.py` constants so routing stays consistent with the rule-based extractors.
- Added `_route_diseasesyptom_by_context(section_type, subsection_type) -> Optional[str]` and `route_diseasesyptom_candidates(candidates, lines, drop_without_context=True) -> List[SpanCandidate]`. Pending candidates overlapping a line resolve to `CHẨN_ĐOÁN` or `TRIỆU_CHỨNG`; pending candidates with no overlapping line are dropped (conservative default).
- Added `VIETMED_DEFAULT_THRESHOLDS` dict: `THUỐC=0.75`, `TÊN_XÉT_NGHIỆM=0.70`, `KẾT_QUẢ_XÉT_NGHIỆM=0.80`, `CHẨN_ĐOÁN=0.80`, `TRIỆU_CHỨNG=0.80` — matches plan §5 starting points. Only fills in thresholds the caller didn't override.
- `ViHealthBERTNER.__init__` accepts `label_map: str = "compact"` and validates against `{"compact", "vietmed"}`.
- `ViHealthBERTNER.predict_windows()` maps labels when `label_map == "vietmed"`, then **always** runs `route_diseasesyptom_candidates` in vietmed mode (routing runs even when `lines` is empty so pending candidates without context are dropped instead of leaking through the threshold filter).
- `ViHealthBERTNER.predict_document()` now passes `document.lines` to `predict_windows`.
- `HuggingFaceTokenPredictor.__init__` accepts `label_map` and validates it. In the PEFT branch, `peft_kwargs` only carries `num_labels` / `id2label` / `label2id` when `label_map == "compact"` — protects the VietMed coarse label space from being clobbered by the compact config.

#### `scripts/build_new_arch_outputs.py`

- Added `--ner-label-map` argparse argument with `choices=["compact", "vietmed"]` and default `"compact"`.
- `run_ner()` accepts `label_map`, fills missing thresholds with `VIETMED_DEFAULT_THRESHOLDS`, and forwards `label_map` to both the predictor and `ViHealthBERTNER`.
- `main()` passes `args.ner_label_map` to `run_ner` and logs when vietmed mode is active.

#### `tests/test_vihealthbert_ner.py`

- Added 10 test functions:
  - `test_map_vietmed_label_high_signal_types`
  - `test_map_vietmed_label_diseasesyptom_marks_pending`
  - `test_map_vietmed_label_drops_non_target_and_zero`
  - `test_diseasesyptom_routing_diagnosis_and_symptom_context`
  - `test_diseasesyptom_routing_drops_without_context`
  - `test_vietmed_label_map_pipeline_decodes_drugs_diag_lab`
  - `test_vietmed_label_map_drops_non_target_labels`
  - `test_vietmed_label_map_drops_pending_without_section_context`
  - `test_compact_label_map_unchanged_by_default`
  - `test_unknown_label_map_rejected`
- Added `__main__` stdlib test runner using `inspect.getmembers` so tests can run without pytest.

### Test results

`python tests/test_vihealthbert_ner.py` (run from `ViClinicalIE/`):

- `ok test_map_vietmed_label_high_signal_types`
- `ok test_map_vietmed_label_diseasesyptom_marks_pending`
- `ok test_map_vietmed_label_drops_non_target_and_zero`
- `ok test_diseasesyptom_routing_diagnosis_and_symptom_context`
- `ok test_diseasesyptom_routing_drops_without_context`
- `ok test_vietmed_label_map_pipeline_decodes_drugs_diag_lab`
- `ok test_vietmed_label_map_drops_non_target_labels`
- `ok test_vietmed_label_map_drops_pending_without_section_context`
- `ok test_compact_label_map_unchanged_by_default`
- `ok test_unknown_label_map_rejected`
- `ok test_bioes_decoding_preserves_raw_vietnamese_span_and_confidence`
- `ok test_decoder_repairs_orphan_inside_label_and_type_transition`
- `ok test_window_inference_maps_local_offsets_and_deduplicates_overlap`
- `ok test_type_threshold_filters_low_confidence_candidates`
- `ok test_predict_preprocessed_uses_offset_safe_model_windows`
- `ok test_predictor_offsets_cannot_exceed_window`

3 pre-existing tests (`test_run_ner_falls_back_when_checkpoint_has_no_fast_tokenizer`, `test_run_ner_strict_reraises_fast_tokenizer_error`, `test_run_ner_falls_back_on_general_backend_init_failure`) require `monkeypatch` / `capsys` pytest fixtures and are not runnable under the stdlib runner (pytest is not installed in this environment). These are pre-existing failures unrelated to this change.

### Bug found and fixed during testing

`predict_windows` initially gated the routing step on `if self.label_map == "vietmed" and lines:`. When `lines=[]` (as exercised by `test_vietmed_label_map_drops_pending_without_section_context`), routing was skipped entirely and pending `_DISEASESYMTOM_PENDING` candidates leaked through the threshold filter because their `thresholds.get(pending, 0.0)` returned `0.0`. The conservative default per plan §Risk controls and §2 ("start conservative") requires dropping pending candidates without context. Fix: changed the gate to `if self.label_map == "vietmed":` — routing always runs in vietmed mode and `route_diseasesyptom_candidates(..., drop_without_context=True)` drops pending candidates with no overlapping line.

### Remaining (Step 7 — ablation)

Not implemented; deferred until the team runs the empirical evaluation on `silver_test`:

- baseline `--skip-ner`
- current NER without mapping (should add near-zero useful spans)
- mapped VietMed NER (`--ner-label-map vietmed`)
- compare span/type/full-entity F1 and inspect false positives
- decide per-type enable/disable by metric gain
