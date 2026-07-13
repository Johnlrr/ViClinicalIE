# ViClinicalIE

Rule-first clinical information extraction and normalization system for the Viettel AI Race clinical text task.

Current repository status: **Phase 8 baseline complete** — the project can run the modular pipeline through:

```text
preprocess + offset mapping
→ section detection
→ baseline span extraction
→ deterministic type resolution
→ deterministic assertion detection
→ ICD-10 candidate generation for CHẨN_ĐOÁN
→ RxNorm candidate generation for THUỐC
```

It is **not yet a final end-to-end submission system**. The next major work is to add merge/postprocess, JSON formatting, validation, golden evaluation, Streamlit review UI, and final inference/submission packaging.

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

For the current Phase 8 baseline, useful targeted checks are:

```cmd
set PYTHONUTF8=1
python -m pytest -q tests\test_candidate_selector.py tests\test_icd10_linker.py tests\test_drug_parser.py tests\test_rxnorm_linker.py
python scripts\run_phase8_smoke.py --config configs\default.yaml --max-files 2 --sample-limit 10
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

### Hiện tại đã done tới Phase 8 chưa?

**Có, nhưng cần hiểu đúng phạm vi:** repo đã done **Phase 8 baseline/module-level**, chưa done hệ thống submit end-to-end.

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
```

Phase 8 không có nghĩa là đã tạo được `output.zip` cuối cùng. Các phần còn thiếu để submit gồm merge/postprocess, JSON formatter, validator, inference CLI, golden evaluator, UI review và packaging.

### Kết quả re-check mới nhất

Ngày 2026-07-13, targeted checks cho Phase 7/8 đã chạy lại thành công:

```text
19 passed in 1.52s

Phase 8 smoke checks completed.
files_checked: 2
chunks_checked: 74
span_candidates: 64
final_entities: 57
diagnosis_entities: 17
diagnosis_with_icd_candidates: 1
drug_entities: 4
drug_with_rxnorm_candidates: 4
offset_error_count: 0
mutation_error_count: 0
invalid_icd_candidate_error_count: 0
invalid_rxnorm_candidate_error_count: 0
wrong_type_candidate_error_count: 0
```

Điều này xác nhận:

- Tests cho candidate selector, ICD linker, drug parser, RxNorm linker đều pass.
- Phase 8 smoke chạy được trên subset golden.
- Linker không làm lệch offset.
- Linker không tự ý đổi span/type/assertion.
- Không có candidate ICD/RxNorm sai loại entity trong smoke check.

Known issue vẫn còn: extractor/type resolver baseline có false positive, ví dụ `caffeine` trong text có thể bị xem như thuốc và được link RxNorm. Đây là lỗi chất lượng cần xử lý ở Phase 10 postprocess và Phase 12/9 calibration, không phải lỗi crash/blocker của Phase 8.

## Not Yet Implemented

- Candidate reranking/calibration beyond current deterministic sparse/linker scoring.
- Global merge/postprocess and overlap resolution.
- Final JSON formatter and schema/offset validator.
- End-to-end `src/pipeline.py` and `scripts/run_inference.py`.
- Golden evaluator and error reports.
- Streamlit validation UI.
- Submission zip creator and source-package rebuild instructions.

## Recommended Next Work

The practical next milestone is to turn the module-level Phase 8 baseline into an end-to-end valid baseline:

```text
Phase 10 minimal merge/postprocess
→ Phase 11 formatter + validator
→ minimal pipeline/run_inference on golden
→ Phase 12 golden evaluator
→ Phase 9/10 calibration and reranking refinements
→ Streamlit UI
```

Roadmap chi tiết hơn:

1. **Phase 10 — Merge/postprocess:** deduplicate spans, xử lý overlap, trim span quá dài/quá ngắn, lọc false positives rõ ràng.
2. **Phase 11 — Formatter/validator:** sinh JSON đúng schema và bắt buộc kiểm `raw_text[start:end] == text`.
3. **Minimal pipeline + inference CLI:** ghép Phase 2–8 + Phase 10/11 để chạy một lệnh trên golden/raw input.
4. **Phase 12 — Golden evaluator:** đo trên 20 gold files, sinh FP/FN/type/candidate/assertion reports.
5. **Phase 9 — Reranking/calibration:** tune ICD/RxNorm thresholds dựa trên evaluator thay vì cảm tính.
6. **Phase 13 — Streamlit UI:** xem raw text, highlight prediction/gold, debug section/span/candidate/assertion.
7. **Phase 14/15 — NER + dense/reranker:** chỉ nên làm sau khi rule baseline và evaluator ổn.
8. **Phase 16/17 — Final inference + packaging:** tạo đủ `output/{id}.json`, validate, zip, và README rebuild cho BTC.



