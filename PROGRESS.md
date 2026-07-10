# PROGRESS: ViClinicalIE implementation state

**Last updated:** 2026-07-10  
**Current implementation phase:** Phase 3 complete — section detection baseline  
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
  - Current `project.phase` is `phase_3_section_detection`.
  - Includes ICD/RxNorm parsing config, sparse retrieval config, preprocess/chunking config, and section detection config.
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

## 4. Validation and command reference

### 4.1 Commands that passed in the current session

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

## 5. Known limitations as of Phase 3

The repo is not yet an end-to-end information extraction system.

Not implemented yet:

- `src/extractors/`
  - drug extractor
  - lab/test extractor
  - problem/symptom/diagnosis extractor
  - dictionary extractor
  - NER extractor interface/model integration
- `src/type_resolution/`
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

Current code provides the foundation needed for Phase 4, but does not yet produce competition-format `output/{id}.json` predictions.

---

## 6. Current git/worktree notes

At the time this progress file was drafted, `git status --short` showed Phase 3-related changes not yet committed:

```text
M configs/default.yaml
M src/data_types.py
 M src/preprocess/normalizer.py
 M tests/test_normalizer.py
?? configs/section_patterns.yaml
?? scripts/audit_phase2_phase3.py
?? scripts/run_phase3_smoke.py
?? src/section/
?? tests/test_section_detector.py
```

Before starting major Phase 4 work, consider:

1. Install dependencies and run full tests.
2. Review/commit Phase 3 changes.
3. Update `README.md` to reflect Phase 1–3 progress.

---

## 7. Recommended next work: Phase 4 span extraction baseline

The next implementation target should be **Phase 4 — Span extraction baseline**, following `Implementation Plan.md` section 10.

Recommended order:

### 7.1 Create extractor package and base interface

Add:

```text
src/extractors/
  __init__.py
  base.py
  drug_extractor.py
  lab_extractor.py
  problem_extractor.py
  dictionary_extractor.py
  imaging_extractor.py
  ner_extractor.py
```

The extractor interface should return `list[SpanCandidate]` with raw offsets and source/provenance metadata.

### 7.2 Implement drug extractor first

Why first:

- Drug spans are strongly supported by RxNorm aliases and medication patterns.
- RxNorm candidate score is important for the final metric.

Initial features:

- RxNorm alias exact/fuzzy lookup.
- Manual drug alias table support.
- Regex for dose, unit, route, frequency.
- Span expansion to include nearby dose/route/frequency.
- Conservative fuzzy splitting for dính chữ cases, where offset alignment is reliable.

### 7.3 Implement lab/test extractor

Initial features:

- `data/dictionaries/lab_tests.csv` if not already present.
- Test-value patterns:
  - `<test> là <value>`
  - `<test>: <value>`
  - `<test> <value>`
  - `<test> âm tính/dương tính/bình thường`
- Emit separate `TÊN_XÉT_NGHIỆM` and `KẾT_QUẢ_XÉT_NGHIỆM` spans.

### 7.4 Implement problem extractor

Initial features:

- Symptom-head rules.
- Disease-head rules.
- Dictionary aliases.
- ICD alias lookup as a feature, not as final type decision.
- Conservative span boundary rules that avoid negation triggers and section headings.

### 7.5 Add tests before tuning

Create/extend tests for:

```text
tests/test_drug_extractor.py
tests/test_lab_extractor.py
tests/test_problem_extractor.py
```

Minimum test examples should include:

- `metoprolol 25mg po bid`
- `aspirin 325mg x 1`
- `troponin 0.01`
- `kali là 6.3`
- `tổng phân tích nước tiểu bình thường`
- `đau bụng vùng hạ sườn phải`
- `khó thở khi gắng sức`
- `viêm túi mật cấp`
- `rung nhĩ kèm đáp ứng thất nhanh`

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
```

Then proceed with Phase 4 implementation.

Before writing new extractor code, keep these invariants visible:

```python
assert raw_text[candidate.start:candidate.end] == candidate.text
assert candidate.start < candidate.end
```

Every extractor should log or expose enough provenance to debug later in the Streamlit UI and evaluator.

---

## 10. Summary

The repository currently has a solid foundation through Phase 3:

- canonical config/data layout;
- ICD/RxNorm terminology parsing and sparse retrieval artifacts;
- raw-preserving preprocessing and offset maps;
- chunking with zero observed audit offset errors;
- section detection with pattern config, carry-forward behavior, smoke tests, and audit reporting.

The next major milestone is to implement Phase 4 span extractors while preserving offsets and producing `SpanCandidate` objects that can later feed type resolution, assertions, linking, merge, formatting, validation, and evaluation.