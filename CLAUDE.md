# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Rule-based/deterministic pipeline for Vietnamese clinical information extraction (ViClinicalIE). Given free-form Vietnamese clinical notes (`input/{file_id}.txt`), it detects medical concepts and outputs `outputs/v0*/output/{file_id}.json`: spans of type `TRIỆU_CHỨNG` (symptom), `TÊN_XÉT_NGHIỆM` (lab name), `KẾT_QUẢ_XÉT_NGHIỆM` (lab result), `CHẨN_ĐOÁN` (diagnosis), `THUỐC` (drug), each with `text`, `position` ([start, end] char offsets into the *raw* input), `type`, `assertions` (`isNegated`/`isFamily`/`isHistorical`, only for CHẨN_ĐOÁN/THUỐC/TRIỆU_CHỨNG), and `candidates` (ICD-10 codes for CHẨN_ĐOÁN, RxNorm codes for THUỐC only).

Full task spec, scoring formula (WER on text + Jaccard on assertions/candidates), and worked examples are in `ABOUT.md`. Design rationale and rule catalog are in `Solution_design.md`, `report_pipeline_overview.md`, `report_assertion.md`, `report_span_extraction.md`.

There is no package manifest (no `requirements.txt`/`pyproject.toml` at repo root) — the core pipeline (`src/`, `scripts/`) is pure stdlib. Only `verify_app/` (Streamlit) has its own `requirements.txt`.

## Commands

Build span candidates only:
```powershell
python scripts\build_span_candidates.py
```

Build full V0 pipeline (extraction → assertion → merge → JSON output → zip → validation report):
```powershell
python scripts\build_v0_outputs.py
```

Build V0 output with ICD-10/RxNorm candidate linking (adds mapping step + coverage gate: fails if diagnosis mapping coverage < 80% or drug < 90%; use `--skip-mapping-gate` to bypass, `--only 1,2,7` / `--limit N` to scope to specific file ids):
```powershell
python scripts\build_v0_linked_outputs.py
```

Run tests (no test runner config — each file is a standalone stdlib script):
```powershell
python tests\test_offset.py
python tests\test_section_parser.py
python tests\test_rule_extractors.py
python tests\test_assertion_merge_output.py
python tests\test_linking.py
```

Build an LLM-generated silver test set for offline eval (stdlib only, calls an OpenAI-compatible endpoint):
```powershell
python scripts\build_silver_test.py --base-url <url> --api-key <key> --model <model>
```
Useful flags: `--limit N` (smoke test), `--only 1,2,7`, `--concurrency N`, `--overwrite`. Output goes to `silver_test/output/{file_id}.json` plus `silver_test/silver_manifest.json`.

Run the verify web app (visually diffs raw text against output JSON, flags schema/offset/overlap errors):
```powershell
python -m pip install -r verify_app\requirements.txt
python -m streamlit run verify_app\app.py
```

Generated artifacts (`analysis/`, `outputs/`, `reports/`, `silver_test/output/`) are gitignored; if a build script isn't producing fresh output, check it's actually deleting old JSON in the output dir first (both `build_v0_outputs.py` and `build_v0_linked_outputs.py` clear `output_json_dir/*.json` before writing).

## Architecture

The pipeline is a strict linear stage sequence, each stage consuming/producing plain dataclasses from `src/models.py` (`ClinicalDocument`, `Section`, `Line`, `SpanCandidate`, `EntityOutput`). All positions carried through the pipeline are **raw-text character offsets**, not normalized-text offsets — this is why `offset_mapper.py` and the raw/norm maps on `ClinicalDocument` exist.

1. **`io_utils.py`** — loads `input/*.txt` into `ClinicalDocument` objects.
2. **`normalization.py` + `offset_mapper.py`** — build a normalized text used only for matching, plus bidirectional offset maps back to raw text. Any span found in normalized text must be mapped back to raw offsets before it's valid output.
3. **`section_parser.py`** — splits each document into `Section`/`Line` via alias-based header matching (`SECTION_ALIASES`, `DEFAULT_PARENT_BY_SECTION`, also overridable via `configs/section_aliases.json`). Section type matters downstream: it feeds `time_context` (past/recent_past/current/in_hospital) used by assertion rules, and constrains which extractors run where.
4. **`rule_extractors.py`** — dictionary + regex extraction of `SpanCandidate`s per entity type (lab, drug, diagnosis, symptom), seeded from `data_resources/*_seed_terms.csv` and `data_resources/non_target_medical_terms.csv` (explicit reject list). `dedupe_candidates` and `validate_candidate_offsets` run at the end of extraction — offset validation drops any candidate whose raw-text slice doesn't match its recorded `text`.
5. **`assertion.py`** — assigns `isNegated`/`isHistorical`/`isFamily` to candidates based on local context window + section `time_context`. Populates `SpanCandidate.assertion_candidates`.
6. **`merge.py`** — dedupes/resolves overlapping spans across extractors (e.g. a diagnosis extractor and symptom extractor both matching the same text).
7. **`src/linking/`** (`candidate_linker.py`, `icd10_linker.py`, `rxnorm_linker.py`, `common.py`) — optional stage, only invoked by `build_v0_linked_outputs.py`. Maps CHẨN_ĐOÁN/THUỐC span text to ICD-10/RxNorm codes using `data_resources/icd10_curated_map.csv`, `rxnorm_curated_map.csv`, and `mapping_aliases.csv`/`drug_aliases.csv` as lookup tables. Populates `SpanCandidate.mapping_candidates`.
8. **`output_writer.py`** — converts merged `SpanCandidate`s to `EntityOutput` and writes per-file JSON + `output.zip`. `EntityOutput.to_dict()` is where the "only include `candidates` for CHẨN_ĐOÁN/THUỐC" schema rule is enforced — don't duplicate that filtering logic elsewhere.
9. **`validator.py`** — checks output artifacts against the input file set (missing files, schema shape, offset/text consistency, overlap) and writes `reports/validation_v0*.md`.

`scripts/build_v0_outputs.py` and `scripts/build_v0_linked_outputs.py` both reuse `run_rule_extraction()` (defined in the former) rather than duplicating the extraction call sequence — when changing the extraction pipeline, edit there once.

Two independent output tracks exist: `outputs/v0/` (rule-only, no candidate mapping) and `outputs/v0_linked/` (adds ICD-10/RxNorm linking). Know which one you're modifying/debugging — they share the same upstream stages but diverge at the linking step and have separate validation/mapping reports under `reports/`.

`scripts/build_silver_test.py` and `scripts/score_silver.py` are a separate, LLM-based offline-eval track (not part of the rule pipeline) — used to generate approximate ground truth and score the rule pipeline's output against it, not to produce competition submissions.

## Domain notes

- Output text is Vietnamese; entity type labels and assertion strings are fixed Vietnamese/English literals defined in `ABOUT.md` — don't alter their spelling/casing.
- `position` must always be `[start, end]` offsets into the **raw** input file, 0-indexed, end-exclusive matching Python slicing (`raw_text[start:end] == text`).
- If a predicted span has correct text but wrong `type`, the scoring metric counts it as two wrong entities (a false negative for the true type and a false positive for the predicted type) — type precision matters as much as span accuracy.
