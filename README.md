# ViClinicalIE

Rule-first clinical information extraction and normalization system for the Viettel AI Race clinical text task.

Current repository status: **Phase 12 golden evaluator baseline complete** — the project can run the modular pipeline through:

```text
preprocess + offset mapping
→ section detection
→ baseline span extraction
→ deterministic type resolution
→ deterministic assertion detection
→ ICD-10 candidate generation for CHẨN_ĐOÁN
→ RxNorm candidate generation for THUỐC
→ conservative merge/postprocess cleanup
→ final JSON formatting + schema/offset validation
→ golden evaluation and error reports
```

It is **not yet a final end-to-end submission system**. The next major work is to add a reusable inference pipeline/CLI, then use Phase 12 reports to guide calibration, UI review, and final submission packaging.

## Setup

```bash
pip install -r requirements.txt
```

Optional ML dependencies for later NER and dense retrieval phases:

```bash
pip install -r requirements-ml.txt
```

## Smoke Checks

Validate the canonical data layout and golden offsets:

```bash
python scripts/check_setup.py --config configs/default.yaml
```

Run tests:

```bash
python -m pytest -q
```

For the current Phase 12 baseline, useful targeted checks are:

```cmd
set PYTHONUTF8=1
python -m pytest -q tests\test_candidate_selector.py tests\test_icd10_linker.py tests\test_drug_parser.py tests\test_rxnorm_linker.py tests\test_postprocess_span_utils.py tests\test_postprocess_cleanup.py tests\test_postprocess_merge.py tests\test_postprocessor.py tests\test_json_formatter.py tests\test_prediction_schema_validator.py tests\test_file_validator.py tests\test_evaluation_span_matcher.py tests\test_evaluation_metrics.py tests\test_evaluator.py
python scripts\run_phase8_smoke.py --config configs\default.yaml --max-files 2 --sample-limit 10
python scripts\run_phase10_smoke.py --config configs\default.yaml --max-files 2 --sample-limit 5
python scripts\run_validate.py --config configs\default.yaml --input-dir data\golden\input --pred-dir data\golden\gold --report-dir outputs\reports\golden_schema_validation --expected-count 20
python scripts\run_phase11_smoke.py --config configs\default.yaml --max-files 2 --sample-limit 5
python scripts\run_evaluate.py --config configs\default.yaml --input-dir data\golden\input --gold-dir data\golden\gold --pred-dir data\golden\gold --report-dir outputs\reports\phase12_gold_self_eval --expected-count 20
```

`PYTHONUTF8=1` is recommended on Windows when paths/usernames contain Vietnamese characters.

## Canonical Data Layout

- `data/raw/input/`: public input files `1.txt` through `100.txt`.
- `data/golden/input/`: copied raw input files for the 20 golden examples.
- `data/golden/gold/`: golden annotations for IDs `1` through `20`.
- `data/terminologies/icd10_byt.csv`: ICD-10 source table.
- `data/terminologies/RXNCONSO.RRF`: RxNorm source table.

Root-level source files are intentionally left in place.

## Implemented Modules by Phase

- **Phase 0:** repo skeleton, config/path loading, IO utilities, logging helpers, shared dataclasses.
- **Phase 1:** ICD-10/RxNorm parsing, alias tables, sparse BM25/TF-IDF retrieval artifacts.
- **Phase 2:** raw-preserving preprocessing, offset mapping, chunking.
- **Phase 3:** section detection. A section is a structural part of a clinical note such as `Tiền sử bệnh`, `Thuốc trước khi nhập viện`, `Kết quả xét nghiệm`; it is used as a prior/context feature, not as a hard rule.
- **Phase 4:** baseline span candidates from dictionary, drug, lab, imaging, problem extractors; NER interface is present but disabled.
- **Phase 5:** deterministic type resolution to one of the five required entity types.
- **Phase 6:** deterministic mention-level assertion detection (`isNegated`, `isHistorical`, `isFamily`).
- **Phase 7:** ICD-10 linker wrapper for `CHẨN_ĐOÁN` entities.
- **Phase 8:** RxNorm linker wrapper and drug parser for `THUỐC` entities.
- **Phase 10:** Conservative postprocessor for exact duplicates, overlap cleanup, safe span trimming, clear false-positive filtering, and candidate/assertion cleanup.
- **Phase 11:** Final JSON formatter plus schema/file/directory validator and Phase 11 smoke writer.
- **Phase 12:** Golden evaluator with exact/relaxed matching, per-file/per-type metrics, assertion/candidate metrics, and JSONL/CSV/Markdown error reports.

## Ghi chú nhanh bằng tiếng Việt

### `section` là gì?

Trong repo này, **section** là nhãn cấu trúc cho từng đoạn/chunk của bệnh án, ví dụ:

- `PAST_HISTORY`: tiền sử bệnh.
- `PRE_ADMISSION_MEDICATION`: thuốc trước khi nhập viện.
- `CURRENT_SYMPTOM`: triệu chứng hiện tại / triệu chứng khi nhập viện.
- `LAB_RESULT`: kết quả xét nghiệm.
- `IMAGING_RESULT`: kết quả chẩn đoán hình ảnh.
- `PROCEDURE`: thủ thuật.
- `DIAGNOSIS_FINDING`: phát hiện/chẩn đoán khác.

Section giúp pipeline hiểu **ngữ cảnh** của một span, nhưng **không được dùng như luật cứng**. Ví dụ:

- Một thuốc trong section `Thuốc trước khi nhập viện` thường có khả năng `isHistorical` cao.
- Nhưng một thuốc kiểu `aspirin 325mg x 1` trong diễn biến cấp cứu không nên bị gán historical chỉ vì nằm gần đoạn trước nhập viện.
- Một triệu chứng trong section tiền sử có thể là tiền sử thật, nhưng cũng có thể là triệu chứng hiện tại được nhắc lại.

Vì vậy, section hiện được dùng như **feature/prior** cho extractor, type resolver và assertion detector. Quyết định cuối vẫn dựa trên mention-level context: cue phủ định, cue tiền sử, người trải nghiệm triệu chứng, thuốc đang dùng hay thuốc mới được chỉ định, v.v.

### Hiện tại đã done tới Phase 12 chưa?

**Có, nhưng cần hiểu đúng phạm vi:** repo đã done **Phase 12 baseline/module-level**, chưa done hệ thống submit end-to-end cho 100 files.

Đã có thể chạy chuỗi module:

```text
raw text
→ preprocess/chunk/offset mapping
→ section detection
→ span extraction baseline
→ type resolution
→ assertion detection
→ ICD-10 linking cho CHẨN_ĐOÁN
→ RxNorm linking cho THUỐC
→ postprocess merge/cleanup
→ format JSON + validate schema/offset
→ evaluate against golden + write error reports
```

Phase 12 không có nghĩa là đã tạo được `output.zip` cuối cùng. Các phần còn thiếu để submit gồm inference CLI/pipeline cho 100 files, UI review và packaging.

### Kết quả re-check mới nhất

Ngày 2026-07-13, targeted checks cho Phase 12 đã chạy thành công:

```text
147 passed in 1.97s

Prediction validation completed.
input_files_checked: 20
prediction_files_checked: 20
entities_checked: 525
error_count: 0
warning_count: 0

Golden evaluation completed.
files_evaluated: 20
gold_entities: 370
pred_entities: 525
exact_f1: 0.1788
relaxed_f1: 0.3642
assertion_exact_match_rate: 0.5658
candidate_hit_rate: 0.4000
```

Điều này xác nhận:

- Full test suite pass.
- Golden schema validation pass với `error_count = 0`; 14 warnings là duplicate exact có sẵn trong golden.
- Phase 11 smoke format/write/validate predictions chạy được trên subset golden và theo batch 20 golden files.
- Formatter không xuất debug fields như `confidence`/`provenance`.
- Validator bắt schema, offset, assertion, candidate và file-level errors.
- Predictions sinh từ Phase 11 smoke có offset đúng, không candidate sai type, không assertion invalid.
- Phase 12 gold-vs-gold self-match đạt exact/relaxed F1 = 1.0, chứng minh matcher xử lý duplicate gold đúng.
- Phase 12 evaluator chạy trên 20 accumulated Phase 11 predictions và sinh reports tại `outputs/reports/phase12_eval_golden20`.

Known issue vẫn còn: repo chưa có inference CLI reusable cho toàn bộ 100 raw files; quality baseline hiện còn thấp và nên dùng Phase 12 reports để tune có kiểm soát.

## Not Yet Implemented

- Candidate reranking/calibration beyond current deterministic sparse/linker scoring.
- End-to-end `src/pipeline.py` and `scripts/run_inference.py`.
- Streamlit validation UI.
- Submission zip creator and source-package rebuild instructions.

## Recommended Next Work

The practical next milestone is to turn the module-level Phase 12 baseline into an end-to-end valid baseline:

```text
minimal pipeline/run_inference on golden/raw input
→ Phase 9/10 calibration and reranking refinements
→ Streamlit UI
```

Roadmap chi tiết hơn:

1. **Minimal pipeline + inference CLI:** ghép Phase 2–8 + Phase 10/11 để chạy một lệnh trên golden/raw input.
2. **Phase 9/10/4/6/7/8 calibration:** tune dựa trên Phase 12 evaluator thay vì cảm tính.
3. **Phase 13 — Streamlit UI:** xem raw text, highlight prediction/gold, debug section/span/candidate/assertion.
4. **Phase 14/15 — NER + dense/reranker:** chỉ nên làm sau khi rule baseline và evaluator ổn.
5. **Phase 16/17 — Final inference + packaging:** tạo đủ `output/{id}.json`, validate, zip, và README rebuild cho BTC.



