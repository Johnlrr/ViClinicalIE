# PROGRESS: ViClinicalIE implementation state

**Last updated:** 2026-07-10  
**Current implementation phase:** Phase 5 complete — deterministic type resolution baseline  
**Reference docs:** `ABOUT.md`, `Solution Design.md`, `Implementation Plan.md`

---

## 1. Project goal

This repository is being built for the Viettel AI Race clinical text entity extraction and normalization task.

The final system must read free-form Vietnamese/mixed clinical notes and output one JSON file per input file containing detected medical concepts with:

- `text`: exact raw substring.
- `position`: `[start, end)` character offsets in raw input.
- `type`: one of:
  - `TRIỆU_CHỨNG`
  - `TÊN_XÉT_NGHIỆM`
  - `KẾT_QUẢ_XÉT_NGHIỆM`
  - `CHẨN_ĐOÁN`
  - `THUỐC`
- `assertions`: only meaningful for `TRIỆU_CHỨNG`, `CHẨN_ĐOÁN`, `THUỐC`; valid values are `isNegated`, `isFamily`, `isHistorical`.
- `candidates`: ICD-10 codes for `CHẨN_ĐOÁN`, RxNorm RxCUIs for `THUỐC`.

The solution direction remains:

```text
Rule-first + Retrieval-first + Encoder-assisted + Validator-enforced
```

Important design constraints from `Solution Design.md` and `Implementation Plan.md`:

1. **Never break raw offsets.** All final spans must satisfy `raw_text[start:end] == text`.
2. **Section detection is only a prior**, not a hard rule for type or assertion.
3. **Entity linking is downstream of extraction/type resolution.** ICD/RxNorm linkers should not invent spans.
4. **Candidate precision matters.** Do not return arbitrary top-k candidates.
5. **Local/self-host only for model inference.** No external APIs for final inference.

---

## 2. Current repository state

### 2.1 Data layout and foundation are in place

Implemented foundation files include:

- `src/config.py`
  - YAML config loading.
  - Project-root-relative path resolution.
- `src/io_utils.py`
  - Text, JSON, JSONL read/write helpers.
- `src/logging_utils.py`
  - Run report directory and summary helpers.
- `src/data_types.py`
  - Shared dataclasses and constants:
    - `TextViews`
    - `Chunk`
    - `PreprocessOutput`
    - `SpanCandidate`
    - `FinalEntity`
    - `MappingCandidate`
    - `VALID_ENTITY_TYPES`
    - `VALID_ASSERTIONS`
- `configs/default.yaml`
  - Current `project.phase` is `phase_5_type_resolution`.
  - Includes ICD/RxNorm parsing config, sparse retrieval config, preprocess/chunking config, section detection config, Phase 4 extractor enable/threshold config, and Phase 5 type-resolution config.
- `configs/paths.yaml`
  - Canonical paths for raw input, terminology files, processed indices, golden data, predictions, reports, and submissions.

Current data status from `scripts/check_setup.py`:

- `data/raw/input/`: 100 raw `.txt` files detected.
- `data/golden/input/` + `data/golden/gold/`: 20 golden input/gold pairs detected.
- Golden annotation entity count: 370.

Root-level `golden_dataset/*.json` still exists, but canonical golden paths are under `data/golden/`.

---

## 3. Completed phases

## 3.1 Phase 0 — project foundation

**Status:** Complete for current scope.

Implemented:

- Repo skeleton and canonical folders:
  - `configs/`
  - `data/`
  - `outputs/`
  - `scripts/`
  - `src/`
  - `tests/`
  - `streamlit_app/`
- Config/path loading.
- IO utilities.
- Basic logging/report directory utilities.
- Data type definitions.
- Setup validation script:
  - `scripts/check_setup.py`

Known caveat:

- `README.md` still describes the project as Phase 0 only. It should be updated after Phase 3/Phase 4 documentation stabilizes.

---

## 3.2 Phase 1 — terminology resources and sparse retrieval

**Status:** Implemented and smoke-tested.

Implemented modules:

- `src/linking/terminology_normalizer.py`
  - Unicode normalization.
  - Whitespace normalization.
  - Vietnamese diacritics removal.
  - Lookup normalization.
  - Code normalization.
  - Lookup tokenization.
- `src/linking/icd10_index.py`
  - Reads `data/terminologies/icd10_byt.csv`.
  - Builds normalized ICD-10 concept/index table.
  - Builds alias table including manual aliases.
- `src/linking/rxnorm_index.py`
  - Reads `data/terminologies/RXNCONSO.RRF`.
  - Filters useful RxNorm rows by config.
  - Parses strength from drug strings.
  - Guesses ingredient and dose form.
  - Builds RxNorm concept/index and alias tables.
- `src/linking/sparse_retriever.py`
  - Builds TF-IDF char n-gram artifacts.
  - Builds BM25 artifacts.
  - Provides sparse alias retrievers returning `MappingCandidate` objects.

Implemented scripts:

- `scripts/build_icd10_index.py`
- `scripts/build_rxnorm_index.py`
- `scripts/build_all_indices.py`
- `scripts/run_phase1_smoke.py`

Expected/generated processed resources:

- `data/processed/icd10_index.parquet`
- `data/processed/icd10_aliases.parquet`
- `data/processed/rxnorm_index.parquet`
- `data/processed/rxnorm_aliases.parquet`
- `data/processed/vector_indices/` sparse artifacts

Smoke check result from current session:

```text
Phase 1 smoke checks passed.
```

Notes:

- Phase 1 currently provides terminology indexing and retrieval primitives, not final linker modules such as `icd10_linker.py` or `rxnorm_linker.py`.
- Dense retrieval and reranking are not implemented yet.

---

## 3.3 Phase 2 — preprocessing, offset mapping, and chunking

**Status:** Implemented and smoke/audit-tested.

Implemented modules:

- `src/preprocess/normalizer.py`
  - Main function: `build_text_views(raw_text, config)`.
  - Produces raw-preserving views:
    - `raw`
    - `normalized`
    - `search`
    - `no_diacritics`
    - `norm_to_raw`
    - `search_to_raw`
    - `no_diacritics_to_raw`
  - Important design decision: no unsafe abbreviation expansion in mapped views, because expansion can break one-to-one offset mapping.
- `src/preprocess/offset_mapper.py`
  - `map_view_span_to_raw(...)`
  - `safe_slice(...)`
  - `assert_raw_span(...)`
  - `repair_span_to_raw_text(...)`
- `src/preprocess/chunker.py`
  - `preprocess_text(raw_text, config)` returns `PreprocessOutput`.
  - `chunk_text(raw_text, config)` splits by line and long-span punctuation/whitespace while preserving raw offsets.

Tests exist for:

- `tests/test_normalizer.py`
- `tests/test_offset_mapper.py`
- `tests/test_chunker.py`

Smoke check result from current session:

```text
Phase 2 smoke checks passed.
files_checked: 6
chunks_created: 189
```

Audit result from `scripts/audit_phase2_phase3.py`:

```text
files_checked: 120
offset_error_count: 0
invalid_section_count: 0
```

This is an important milestone: current preprocessing/chunking did not produce raw offset mismatches across 100 raw files + 20 golden files in the audit.

---

## 3.4 Phase 3 — section detection

**Status:** Implemented and smoke/audit-tested.

Implemented files:

- `configs/section_patterns.yaml`
  - Pattern config for section labels such as:
    - `PAST_HISTORY`
    - `PAST_MEDICAL_HISTORY`
    - `PRE_ADMISSION_MEDICATION`
    - `CURRENT_ILLNESS`
    - `ADMISSION_REASON`
    - `CURRENT_SYMPTOM`
    - `SYMPTOM_CHARACTERISTIC`
    - `PRE_ADMISSION_EVENT`
    - `HOSPITAL_ASSESSMENT`
    - `PHYSICAL_EXAM`
    - `LAB_RESULT`
    - `IMAGING_RESULT`
    - `PROCEDURE`
    - `TREATMENT`
    - `DIAGNOSIS_FINDING`
    - `UNKNOWN`
- `src/section/section_detector.py`
  - `SECTION_LABELS`
  - `SectionMatch`
  - `SectionDetector`
  - `load_section_patterns(...)`
  - `detect_sections(...)`
  - Heading normalization/matching helpers.
- `src/section/__init__.py`
- `scripts/run_phase3_smoke.py`
- `scripts/audit_phase2_phase3.py`
- `tests/test_section_detector.py`

Current section detector behavior:

- Detects exact heading matches.
- Detects no-diacritics heading matches.
- Detects contained/inline headings before `:`.
- Strips common bullet/numbering markers.
- Carries the current section forward to subsequent chunks.
- Assigns:
  - `chunk.section`
  - `chunk.section_confidence`
  - `chunk.section_source`
  - optional `chunk.subsection`

Smoke check result from current session:

```text
Phase 3 smoke checks passed.
files_checked: 6
chunks_checked: 189
section_counts: {
  'ADMISSION_REASON': 4,
  'CURRENT_ILLNESS': 17,
  'CURRENT_SYMPTOM': 31,
  'DIAGNOSIS_FINDING': 8,
  'HOSPITAL_ASSESSMENT': 10,
  'IMAGING_RESULT': 9,
  'LAB_RESULT': 12,
  'PAST_HISTORY': 34,
  'PHYSICAL_EXAM': 3,
  'PRE_ADMISSION_EVENT': 25,
  'PRE_ADMISSION_MEDICATION': 11,
  'PROCEDURE': 8,
  'SYMPTOM_CHARACTERISTIC': 17
}
```

Full Phase 2/3 audit result:

```text
Phase 2/3 audit completed.
files_checked: 120
offset_error_count: 0
invalid_section_count: 0
section_counts: {
  'ADMISSION_REASON': 228,
  'CURRENT_ILLNESS': 312,
  'CURRENT_SYMPTOM': 499,
  'DIAGNOSIS_FINDING': 119,
  'HOSPITAL_ASSESSMENT': 109,
  'IMAGING_RESULT': 156,
  'LAB_RESULT': 211,
  'PAST_HISTORY': 576,
  'PAST_MEDICAL_HISTORY': 6,
  'PHYSICAL_EXAM': 118,
  'PRE_ADMISSION_EVENT': 420,
  'PRE_ADMISSION_MEDICATION': 101,
  'PROCEDURE': 150,
  'SYMPTOM_CHARACTERISTIC': 467,
  'TREATMENT': 48,
  'UNKNOWN': 8
}
source_counts: {
  'carry_forward': 2104,
  'containment_heading': 123,
  'containment_inline': 44,
  'containment_no_diacritics_heading': 3,
  'default': 8,
  'exact_heading': 675,
  'exact_inline': 571
}
unmatched_heading_like_count: 1165
report: outputs/reports/phase2_phase3_audit/summary.json
```

Interpretation of `unmatched_heading_like_count`:

- Many top examples are carried-forward bullet content such as `- mệt mỏi`, `- ho`, `- tăng huyết áp`, etc.
- These are often entity/list items under an already detected section, not necessarily missing headings.
- Keep this audit useful for future improvements, but do not treat all unmatched heading-like rows as section detector failures.

Important caveat:

- Section detection must remain a **feature/prior only**. Do not hardcode entity type or assertion purely from section labels.

---

## 3.5 Phase 4 — span extraction baseline

**Status:** Baseline implemented and smoke-tested.

Phase 4 adds the first extractor layer. It does **not** yet produce final competition JSON and does **not** yet perform final type resolution, assertion detection, overlap merging, or ICD/RxNorm final candidate selection. Its purpose is to emit raw-offset-safe `SpanCandidate` objects for later phases.

Implemented files:

- `configs/entity_rules.yaml`
  - Initial configurable rule lists for drug units/routes/frequencies, qualitative lab results, symptom heads, and disease heads.
- `data/dictionaries/lab_tests.csv`
  - Baseline lab/test aliases such as WBC, RBC, HGB, kali, creatinine, troponin, INR, UA, cấy máu, cấy nước tiểu.
- `data/dictionaries/symptoms_vi.csv`
  - Baseline symptom aliases such as đau bụng, đau ngực, khó thở, ho, sốt, buồn nôn, chóng mặt, mệt mỏi, phù, mất ngủ, lú lẫn.
- `src/extractors/base.py`
  - `ExtractionContext` and `BaseExtractor` interface.
- `src/extractors/utils.py`
  - Shared candidate construction, raw-span validation, context extraction, candidate deduplication, phrase matching, punctuation trimming, and overlap helpers.
- `src/extractors/dictionary_extractor.py`
  - Conservative exact/no-diacritics dictionary matcher.
  - Includes a guard against short accent-insensitive false positives such as matching `phù` to `phụ`.
- `src/extractors/drug_extractor.py`
  - RxNorm/manual alias based baseline drug extractor.
  - Expands adjacent dose/route/frequency tokens.
  - Handles sentence-final punctuation during alias prefiltering, e.g. `atenolol.`.
- `src/extractors/lab_extractor.py`
  - Lab/test alias matcher.
  - Emits separate `TÊN_XÉT_NGHIỆM` and `KẾT_QUẢ_XÉT_NGHIỆM` candidates when simple value/result patterns are found.
- `src/extractors/imaging_extractor.py`
  - Baseline cận lâm sàng/imaging test extractor for X-ray, CT, MRI, ultrasound, ECG/EKG, Holter, xạ hình, etc.
- `src/extractors/problem_extractor.py`
  - Baseline symptom/disease-head extractor emitting provisional `TRIỆU_CHỨNG` or `CHẨN_ĐOÁN` candidates.
- `src/extractors/ner_extractor.py`
  - No-op NER extractor interface, disabled by default.
- `src/extractors/__init__.py`
  - `build_default_extractors(config)` factory.
- `scripts/run_phase4_smoke.py`
  - Runs preprocess → section detection → enabled extractors → raw-offset validation.
- Tests added:
  - `tests/test_extractor_base.py`
  - `tests/test_dictionary_extractor.py`
  - `tests/test_drug_extractor.py`
  - `tests/test_lab_extractor.py`
  - `tests/test_imaging_extractor.py`
  - `tests/test_problem_extractor.py`

Manual validation in the current environment:

```text
python -m compileall -q src\extractors scripts\run_phase4_smoke.py
manual_tests_passed 11
```

`pytest` is still unavailable in the active interpreter, so extractor tests were executed manually by importing each `test_*` function.

Phase 4 smoke on 20 golden input files:

```text
Phase 4 smoke checks completed.
files_checked: 20
chunks_checked: 700
total_candidates: 667
candidate_count_by_source: {
  'dictionary': 134,
  'drug_rule': 23,
  'imaging_rule': 55,
  'lab_result_rule': 5,
  'lab_rule': 15,
  'problem_rule': 435
}
candidate_count_by_raw_type: {
  'CHẨN_ĐOÁN': 212,
  'KẾT_QUẢ_XÉT_NGHIỆM': 5,
  'THUỐC': 23,
  'TRIỆU_CHỨNG': 357,
  'TÊN_XÉT_NGHIỆM': 70
}
offset_error_count: 0
```

Known Phase 4 caveats:

- This is a **candidate generation baseline**, not a calibrated final extractor.
- `problem_extractor.py` is intentionally recall-oriented and can over-extend spans; Phase 5 type resolution and Phase 10 merge/postprocess must clean this up.
- `drug_extractor.py` uses broad RxNorm aliases and may detect non-medication substance mentions such as `caffeine`; later type/context filtering should reduce false positives.
- `imaging_extractor.py` can over-extend imaging test spans, e.g. including temporal/context words after `siêu âm tim`; later span-boundary tuning is needed.
- `lab_extractor.py` currently catches only simple adjacent result patterns; recall for lab values remains low.
- No final entity merging/deduplication across extractor sources yet.

---

## 3.6 Phase 5 — type resolution

**Status:** Implemented and smoke-tested.

Phase 5 converts exact-offset-safe `SpanCandidate` objects from Phase 4 into provisional `FinalEntity` objects. It remains intentionally narrow: it does **not** assign assertions, does **not** call ICD/RxNorm linkers, does **not** perform global overlap merge, and does **not** format final competition JSON.

Implemented files:

- `src/type_resolution/features.py`
  - `TypeFeatures` deterministic feature dataclass.
  - Feature builders for source, raw type, section, score, lab/drug/imaging evidence, drug context, symptom heads, disease heads, dictionary symptom evidence, and placeholder linkability scores.
  - Explicit helper functions:
    - `build_type_features(...)`
    - `has_drug_context(...)`
    - `has_symptom_head(...)`
    - `has_disease_head(...)`
- `src/type_resolution/resolver.py`
  - `TypeResolver` deterministic resolver.
  - `ResolvedCandidate`, `TypeConflict`, and `TypeOverlap` debug dataclasses.
  - Exact same-span grouping and single provisional entity selection.
  - Explicit type priority and source priority.
  - Same-type exact-span duplicate tracking separate from true type conflicts.
  - Non-destructive overlap logging for Phase 10 analysis.
  - Provenance payloads with chosen source, confidence, priorities, type features, warnings, and all exact-span source candidates.
- `src/type_resolution/__init__.py`
- `tests/test_type_resolver.py`
- `scripts/run_phase5_smoke.py`
  - Runs preprocess → section detection → Phase 4 extractors → Phase 5 resolver.
  - Prints entity counts, true type conflicts, same-type exact duplicates, overlaps, unresolved count, offset errors, and sample entities/debug records.
- `configs/default.yaml`
  - `project.phase: phase_5_type_resolution`.
  - `type_resolution` config with source priorities, type priorities, confidence defaults, and flags.

Current resolver policy:

1. `lab_result_rule` → `KẾT_QUẢ_XÉT_NGHIỆM`.
2. `lab_rule` / `imaging_rule` → `TÊN_XÉT_NGHIỆM`.
3. `drug_rule` → `THUỐC` with lower confidence and `drug_without_context` warning if no medication context is detected.
4. `dictionary` with valid schema type → its raw type.
5. `problem_rule` disease-head evidence → `CHẨN_ĐOÁN`.
6. `problem_rule` symptom-head evidence → `TRIỆU_CHỨNG`.
7. `ner` fallback if enabled later.
8. Controlled fallback to valid raw type; otherwise unresolved log entry.

Exact same-span selection sorts by:

1. type priority;
2. confidence;
3. original candidate score;
4. source priority.

Important Phase 5 design choices:

- Phase 5 does not call ICD/RxNorm retrieval and does not let linkability override type decisions.
- `raw_type` is preserved and can be used as fallback evidence, but high-priority lab/drug evidence is source-driven.
- Same-type duplicate exact spans are not counted as `TypeConflict`; they are retained in provenance and counted as `duplicate_exact_span_count`.
- Different-span overlaps are kept in output and logged as `TypeOverlap` for later Phase 10 merge/postprocess work.

Manual validation in the current environment:

```text
python -m compileall -q src\type_resolution scripts\run_phase5_smoke.py
manual_type_resolver_tests_passed 10
```

`pytest` remains unavailable in the active interpreter, so resolver tests were also executed manually by importing each `test_*` function.

Phase 5 smoke on 20 golden input files:

```text
Phase 5 smoke checks completed.
files_checked: 20
chunks_checked: 700
span_candidates: 667
final_entities: 610
candidate_count_by_source: {
  'dictionary': 134,
  'drug_rule': 23,
  'imaging_rule': 55,
  'lab_result_rule': 5,
  'lab_rule': 15,
  'problem_rule': 435
}
entities_by_type: {
  'CHẨN_ĐOÁN': 212,
  'KẾT_QUẢ_XÉT_NGHIỆM': 5,
  'THUỐC': 23,
  'TRIỆU_CHỨNG': 300,
  'TÊN_XÉT_NGHIỆM': 70
}
conflict_count: 0
duplicate_exact_span_count: 57
overlap_count: 93
unresolved_count: 0
offset_error_count: 0
```

Known Phase 5 caveats:

- Many Phase 4 problem spans are still over-extended. Phase 5 preserves them because global span selection and trimming belong mostly to Phase 10.
- Overlap logs show expected cases like dictionary symptom spans contained in longer problem-rule spans.
- Some Phase 4 false positives remain, e.g. broad drug aliases such as `caffeine`; Phase 5 keeps these with confidence/provenance warnings rather than dropping them prematurely.
- No assertion detection, ICD/RxNorm linker wrappers, final postprocess merge, or JSON formatter/validator has been implemented yet.

---

## 4. Validation and command reference

### 4.1 Commands that passed in this project state

Use Windows `cmd` command chaining in this environment instead of relying on PowerShell `&&` behavior:

```cmd
cmd /d /s /c "python scripts\check_setup.py --config configs\default.yaml & python scripts\run_phase1_smoke.py --config configs\default.yaml & python scripts\run_phase2_smoke.py --config configs\default.yaml --max-files 6 & python scripts\run_phase3_smoke.py --config configs\default.yaml --max-files 6 & python scripts\audit_phase2_phase3.py --config configs\default.yaml --max-unmatched 20"
```

Observed output summary:

```text
Phase 0 setup check passed.
raw_input_files: 100
golden_pairs: 20
golden_entities: 370

Phase 1 smoke checks passed.

Phase 2 smoke checks passed.
files_checked: 6
chunks_created: 189

Phase 3 smoke checks passed.
files_checked: 6
chunks_checked: 189

Phase 2/3 audit completed.
files_checked: 120
offset_error_count: 0
invalid_section_count: 0
```

Phase 4 validation commands passed:

```cmd
python -m compileall -q src\extractors scripts\run_phase4_smoke.py
python scripts\run_phase4_smoke.py --config configs\default.yaml --max-files 20 --sample-limit 5
```

Manual extractor tests passed by importing and running each `test_*` function because `pytest` is not installed in the active interpreter:

```text
manual_tests_passed 11
```

Phase 5 validation commands passed:

```cmd
python -m compileall -q src\type_resolution scripts\run_phase5_smoke.py
python scripts\run_phase5_smoke.py --config configs\default.yaml --max-files 20 --sample-limit 10
```

Manual type resolver tests passed by importing and running each `test_*` function because `pytest` is not installed in the active interpreter:

```text
manual_type_resolver_tests_passed 10
```

### 4.2 Pytest status

Attempted command:

```cmd
python -m pytest -q
```

Current result:

```text
C:\Program Files\Python313\python.exe: No module named pytest
```

`pytest` is listed in `requirements.txt`, so this is an environment/setup issue, not necessarily a test failure. Before relying on tests in a new session, install dependencies in the intended environment:

```cmd
python -m pip install -r requirements.txt
python -m pytest -q
```

If multiple Python installations/venvs exist, ensure the same interpreter is used for dependency installation and test execution.

---

## 5. Known limitations as of Phase 4

The repo is still not an end-to-end competition output system.

Implemented now:

- extractor interfaces and baseline candidate generators under `src/extractors/`;
- baseline dictionaries and entity rules;
- Phase 4 smoke script;
- extractor tests.
- deterministic Phase 5 type-resolution package under `src/type_resolution/`;
- Phase 5 smoke script;
- type resolver tests.

Not implemented yet:

- `src/assertion/`
- final `src/linking/icd10_linker.py` / `rxnorm_linker.py` wrappers
- deterministic reranker module beyond sparse retrieval primitives
- `src/postprocess/`
  - merge overlap
  - calibration
  - output formatter
- `src/validation/`
  - schema validator
  - offset validator for predictions
  - evaluator/diff
- `src/pipeline.py`
- inference CLI for final predictions:
  - `scripts/run_inference.py`
- final validation CLI:
  - `scripts/run_validate.py`
- golden evaluator:
  - `scripts/run_eval_golden.py`
- submission zipper:
  - `scripts/make_submission_zip.py`
- Streamlit validation UI beyond placeholder folder:
  - `streamlit_app/.gitkeep` exists, but no app yet.

Current code can produce Phase 4 `SpanCandidate` objects and Phase 5 provisional `FinalEntity` objects. It still does **not** produce final competition-format `output/{id}.json` predictions.

---

## 6. Current git/worktree notes

Phase 4 added/modified a significant set of files:

```text
configs/default.yaml
configs/paths.yaml
configs/entity_rules.yaml
data/dictionaries/lab_tests.csv
data/dictionaries/symptoms_vi.csv
src/extractors/
scripts/run_phase4_smoke.py
tests/test_extractor_base.py
tests/test_dictionary_extractor.py
tests/test_drug_extractor.py
tests/test_lab_extractor.py
tests/test_imaging_extractor.py
tests/test_problem_extractor.py
PROGRESS.md
```

Phase 5 added/modified:

```text
configs/default.yaml
src/type_resolution/__init__.py
src/type_resolution/features.py
src/type_resolution/resolver.py
scripts/run_phase5_smoke.py
tests/test_type_resolver.py
PROGRESS.md
```

Before starting major Phase 6 work, consider:

1. Install dependencies and run full `pytest`.
2. Review/commit Phase 4–5 changes.
3. Update `README.md` to reflect Phase 1–5 progress.

---

## 7. Recommended next work: Phase 6 assertion detection

The next implementation target should be **Phase 6 — Assertion detection**, following `Implementation Plan.md` section 12.

Goal: assign mention-level assertions to Phase 5 `FinalEntity` objects for clinical problem/drug types while preserving offsets and avoiding section-hardcoded behavior.

Recommended Phase 6 deliverables:

```text
src/assertion/
  __init__.py
  context_rules.py
  negation.py
  historical.py
  family.py
  assertion_detector.py
tests/test_assertion.py
scripts/run_phase6_smoke.py
```

Initial assertion policy:

1. Apply assertions only to `TRIỆU_CHỨNG`, `CHẨN_ĐOÁN`, and `THUỐC`.
2. Detect negation with cue + scope, including list scopes.
3. Detect historical status at mention level using temporal/status cues and current-event overrides.
4. Detect family assertions with high precision, requiring the family member to be the experiencer rather than only the reporter.
5. Keep assertion scores/provenance internally for debugging.

Important Phase 6 caveats:

- Do not assign assertions to lab/test/result types.
- Do not make historical decisions from section label alone.
- Do not mark `isFamily` when a family member is only the observer/reporter.
- Preserve `raw_text[entity.start:entity.end] == entity.text` for all entities.

---

## 8. Later phases after extraction baseline

After Phase 4, continue in this order:

1. **Phase 5 — Type resolution**
   - Resolve conflicts among drug/lab/problem/NER/dictionary candidates.
   - Especially separate `TRIỆU_CHỨNG` vs `CHẨN_ĐOÁN`.
2. **Phase 6 — Assertion detection**
   - ConText-style negation, historical, and family detection.
   - Mention-level, not section-hardcoded.
3. **Phase 7/8 — ICD-10 and RxNorm linker wrappers**
   - Use existing Phase 1 sparse retrievers.
   - Add candidate thresholding and score logs.
4. **Phase 9 — Reranking**
   - Start deterministic; dense/cross-encoder later if needed.
5. **Phase 10 — Merge and postprocess**
   - Deduplication and overlap conflict handling.
6. **Phase 11 — JSON formatter and validator**
   - Enforce schema and `raw_text[start:end] == text`.
7. **Phase 12 — Golden evaluation loop**
   - Validate 20 gold files.
   - Run approximate local metrics and error reports.
8. **Phase 13 — Streamlit UI**
   - Highlight raw text, predictions, gold, and diffs.
9. **Phase 14/15 — NER and dense retrieval/reranker**
   - Only after rule baseline and evaluator are stable.
10. **Phase 16/17 — End-to-end inference and packaging**
   - `run_inference.py`, `run_validate.py`, `make_submission_zip.py`, README rebuild instructions.

---

## 9. Practical continuation checklist

For a future session, start here:

```cmd
python -m pip install -r requirements.txt
python -m pytest -q
python scripts\check_setup.py --config configs\default.yaml
python scripts\run_phase1_smoke.py --config configs\default.yaml
python scripts\run_phase2_smoke.py --config configs\default.yaml --max-files 6
python scripts\run_phase3_smoke.py --config configs\default.yaml --max-files 6
python scripts\audit_phase2_phase3.py --config configs\default.yaml --max-unmatched 20
python scripts\run_phase4_smoke.py --config configs\default.yaml --max-files 20 --sample-limit 5
```

Then proceed with Phase 5 type resolution implementation.
Then proceed with Phase 6 assertion detection implementation.

Before writing new extractor code, keep these invariants visible:

```python
assert raw_text[candidate.start:candidate.end] == candidate.text
assert candidate.start < candidate.end
```

Every resolver/postprocess component should preserve enough provenance to debug later in the Streamlit UI and evaluator.

---

## 10. Summary

The repository currently has a solid foundation through Phase 4:

- canonical config/data layout;
- ICD/RxNorm terminology parsing and sparse retrieval artifacts;
- raw-preserving preprocessing and offset maps;
- chunking with zero observed audit offset errors;
- section detection with pattern config, carry-forward behavior, smoke tests, and audit reporting.
- baseline span extraction package with dictionary, drug, lab, imaging, problem, and no-op NER extractors;
- Phase 4 smoke validation on 20 golden files with zero offset errors.
- deterministic Phase 5 type resolution producing provisional `FinalEntity` objects;
- Phase 5 smoke validation on 20 golden files with zero offset errors.

The next major milestone is to implement Phase 6 assertion detection, assigning negation, historical, and family assertions at mention level while preserving offsets.