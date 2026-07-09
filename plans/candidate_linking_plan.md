# Plan: Fill the `candidates` field via retrieve-then-rerank

## Goal
Populate the `candidates` field (ICD-10 for `CHẨN_ĐOÁN`, RxNorm RXCUI for `THUỐC`) in
`ViClinicalIE/silver_test/output/*.json`, re-filled from scratch, using the two new
knowledge bases:
- `ViClinicalIE/data_resources/icd10_byt_source.csv` (~37k rows, `;`-delimited, BOM, quoted multiline cells)
- `ViClinicalIE/data_resources/RXNCONSO.RRF` (~245k rows, `|`-delimited)

## Why retrieve-then-rerank
An LLM cannot reliably recall 37k ICD codes / 245k RXCUIs and will hallucinate.
The scorer weights `candidates_score` at 0.4 of `final_score` using a Jaccard of
`(concept, code)` sets, and empty-gold-vs-nonempty-pred scores 0 — so hallucinated
codes actively hurt. A local retriever builds a shortlist of *real* codes; the LLM
only selects from that shortlist, so every emitted code provably exists.

## Data field references
- ICD (`icd10_byt_source.csv`): `MÃ BỆNH` = code with dot (e.g. `A00.0`),
  `TÊN BỆNH` = Vietnamese name, `DISEASE NAME WHO 2019 (ENGLISH)` = English name.
  Prefer specific 4+ char codes over 3-char category headers.
- RxNorm (`RXNCONSO.RRF`): field 0 = `RXCUI` (the code to emit), 11 = `SAB`,
  12 = `TTY`, 14 = `STR`, 16 = `SUPPRESS`. Keep `SUPPRESS=N`; prefer `SAB=RXNORM`.

## Reuse
- API client: `chat_completion()` in `scripts/build_silver_test.py` (streaming, retries,
  SSE handling) — already targeting `https://api.shopaikey.com/v1`.
- Normalization + similarity helpers in `src/linking/common.py`.
- Drug dose/route stripping: `DOSE_AND_SIG_PATTERN` in `src/linking/rxnorm_linker.py`.

## Pipeline
1. Local retrievers over the two catalogs -> `top_n(query)` returning real `code + label`.
2. For each `CHẨN_ĐOÁN` / `THUỐC` span in the silver output, build a numbered shortlist.
3. One LLM rerank call per file (batched spans): prompt = span + context sentence +
   numbered shortlist; model returns only listed codes or `[]`.
4. Validate output against the shortlist (drop anything not present), dedupe.
5. Write chosen codes back into `candidates`, preserving text/position/type/assertions.
6. Re-run `scripts/score_silver.py`; confirm `candidates_score` / `final_score` lift.

## New/changed files (proposed)
- `src/linking/icd10_catalog.py` — full-catalog ICD retriever.
- `src/linking/rxnorm_catalog.py` — full-catalog RxNorm retriever.
- `scripts/fill_candidates.py` — orchestration + LLM rerank + write-back + manifest.
- `tests/test_catalog_retrievers.py` — retriever sanity on known spans.

## CLI (mirror build_silver_test.py)
`--base-url --api-key --model --input-dir --output-dir --only --limit --concurrency
--overwrite --temperature --timeout --max-retries --max-tokens --no-stream`,
with `OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL` env fallbacks.
