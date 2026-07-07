# Implementation Plan cho giai đoạn cuộc thi 02/07 – 30/07

## 0. Mục tiêu tài liệu

Tài liệu này là **kế hoạch cài đặt và triển khai dự án trong thời gian cuộc thi**, tập trung vào việc biến thiết kế solution thành hệ thống chạy được, có khả năng sinh `output.zip`, kiểm thử được, cải thiện được qua nhiều vòng submission và có thể đóng gói source code để BTC dựng lại trên private test.

Phạm vi bao gồm:

```text
- Tổ chức repo và môi trường chạy
- Data profiling và structured analysis layer
- Baseline rule/dictionary end-to-end
- ICD/RxNorm candidate mapping
- Assertion detection
- Integration và validator
- First submission
- Error analysis sau submission
- Các vòng cải thiện
- Freeze final solution
- Đóng gói source/model/data/README
```

Giả định lịch cuộc thi:

```text
Ngày bắt đầu: 02/07
Ngày kết thúc: 30/07
```

Nếu hiện tại đã qua một số ngày đầu, các việc thuộc giai đoạn 02/07–06/07 được xem là **setup/research đã hoặc cần hoàn tất bù ngay**.

---

## 1. Nguyên tắc triển khai

### 1.1. Ưu tiên hệ thống chạy được trước

Không bắt đầu bằng model phức tạp. Mục tiêu đầu tiên là có pipeline end-to-end:

```text
input/*.txt
→ parse
→ extract span candidates
→ map ICD/RxNorm nếu cần
→ detect assertion
→ validate offset/schema
→ output/*.json
→ output.zip
```

### 1.2. Mọi module phải test được độc lập

Mỗi module cần có test nhỏ:

```text
- test offset mapping
- test section parser
- test lab/result regex
- test drug parser
- test assertion scope
- test ICD/RxNorm lookup
- test overlap resolver
- test JSON validator
```

### 1.3. Không phụ thuộc API ngoài runtime

Vì BTC có thể dựng lại trên private test, pipeline cần chạy offline:

```text
- ICD/RxNorm dictionary/index phải đi kèm repo hoặc có script build rõ ràng
- Không gọi OpenAI/Google/API ngoài trong inference
- Không hard-code theo 100 public files
```

### 1.4. Tối ưu theo metric thật

Metric chính:

```text
final_score = 0.3 * text_score
            + 0.3 * assertions_score
            + 0.4 * candidates_score
```

Nên ưu tiên:

```text
1. Candidate mapping ICD/RxNorm
2. Span boundary và type
3. Assertion
```

### 1.5. Không để LLM quyết định output trực tiếp

LLM, nếu dùng self-host model hợp lệ, chỉ nên dùng cho:

```text
- fallback cho span mơ hồ
- rerank candidate trong top-k đã có
- review nội bộ / synthetic data
```

Không dùng LLM để sinh toàn bộ JSON một bước vì dễ sai offset, sinh mã không tồn tại và khó debug.

---

## 2. Deliverable tổng thể cần đạt trước 30/07

Đến cuối cuộc thi, cần có các deliverable sau.

### 2.1. Submission deliverable

```text
output.zip
└── output/
    ├── 1.json
    ├── 2.json
    ├── ...
    └── 100.json
```

Mỗi file `.json` phải:

```text
- parse được bằng JSON parser chuẩn
- là list các object
- có text, position, type, assertions
- có candidates cho CHẨN_ĐOÁN và THUỐC
- position khớp raw_text[start:end] == text
- không có type/assertion/candidate field sai schema
```

### 2.2. Code deliverable

```text
repo/
├── README.md
├── requirements.txt hoặc environment.yml
├── predict.py
├── make_output_zip.py
├── configs/
├── data_resources/
├── src/
├── tests/
├── scripts/
├── notebooks/              # optional, không cần cho inference
└── outputs/
```

Lệnh chạy chuẩn:

```bash
python predict.py --input_dir test/input --output_dir output
python make_output_zip.py --output_dir output --zip_path output.zip
```

### 2.3. Data/resource deliverable

```text
data_resources/
├── section_aliases.json
├── assertion_triggers.json
├── drug_aliases.csv
├── drug_context_terms.csv
├── diagnosis_seed_terms.csv
├── symptom_seed_terms.csv
├── lab_seed_terms.csv
├── abbreviation_map.csv
├── non_target_medical_terms.csv
├── noise_normalization.json
├── icd10_index.*
└── rxnorm_index.*
```

### 2.4. Analysis deliverable

```text
analysis/
├── section_inventory.csv
├── line_inventory.csv
├── span_candidates.jsonl
├── error_log.csv
├── submission_history.md
└── ablation_results.md
```

### 2.5. Final packaging deliverable

```text
final_package/
├── source_code.zip
├── output.zip
├── README_RUN.md
├── model_weights/          # nếu có model
├── data_resources/
└── environment file
```

---

## 3. Milestone tổng quan 02/07 – 30/07

| Giai đoạn | Thời gian | Mục tiêu chính | Deliverable |
|---|---:|---|---|
| P0 | 02/07–06/07 | Hiểu đề, đọc data, chốt design | Data assessment + solution plan |
| P1 | 07/07–10/07 | Baseline end-to-end chạy được | V0 output.zip nội bộ |
| P2 | 11/07–13/07 | First valid submission | First public submission |
| P3 | 14/07–18/07 | Cải thiện span/assertion/mapping bằng error analysis | V1/V2 submission |
| P4 | 19/07–23/07 | Tăng recall và optional model/LLM fallback | V3 submission |
| P5 | 24/07–27/07 | Stabilize, ablation, chọn final candidate | Release candidate |
| P6 | 28/07–30/07 | Freeze, final submission, đóng gói source | Final output + source package |

---

## 4. Kế hoạch chi tiết theo giai đoạn

# P0 — Setup, research, data understanding  
**Thời gian:** 02/07–06/07  
**Trạng thái:** Nếu hiện tại đã qua giai đoạn này, cần kiểm tra các deliverable đã có và bổ sung phần thiếu.

## Mục tiêu

```text
- Hiểu format đề bài
- Đọc qua 100 file gộp
- Chốt kiến trúc solution
- Chốt data assessment requirement
- Chuẩn bị repo skeleton
```

## Công việc

### P0.1. Đọc đề và xác nhận schema output

Checklist:

```text
- Xác nhận 5 type hợp lệ
- Xác nhận assertion chỉ gồm isNegated, isFamily, isHistorical
- Xác nhận candidate mapping:
  - CHẨN_ĐOÁN → ICD-10
  - THUỐC → RxNorm
- Xác nhận position là character offset trên raw text
- Xác nhận output.zip structure
```

Deliverable:

```text
docs/problem_summary.md
```

### P0.2. Đọc 100 file và profiling thô

Checklist:

```text
- Tách all.txt thành 100 record theo marker # N.txt
- Đếm số file
- Đếm độ dài từng file
- Liệt kê section/header thường gặp
- Liệt kê lỗi spacing/typo thường gặp
- Liệt kê ví dụ drug/lab/diagnosis/symptom
```

Deliverable:

```text
analysis/data_overview.md
analysis/record_stats.csv
```

### P0.3. Chốt data assessment requirement

Deliverable:

```text
docs/data_assessment.md
```

### P0.4. Chốt solution project plan

Deliverable:

```text
docs/solution_DESIGN.md
```

### P0.5. Tạo repo skeleton

Deliverable:

```text
src/
tests/
configs/
data_resources/
scripts/
analysis/
outputs/
```

---

# P1 — Baseline end-to-end chạy được  
**Thời gian:** 07/07–10/07  
**Mục tiêu:** Có pipeline V0 sinh được JSON cho toàn bộ input.

Đây là giai đoạn quan trọng nhất. Không tối ưu quá sớm. Chỉ cần chạy được, validate được, output đúng schema.

---

## Ngày 07/07 — Input loader, parser, offset foundation

### Công việc

1. Implement input loader:

```text
- Nếu input là folder test/input/*.txt → đọc từng file
- Nếu input là all.txt → tách thành record phục vụ analysis
```

2. Implement raw/normalized text object:

```python
ClinicalDocument(
    file_id,
    raw_text,
    normalized_text,
    norm_to_raw_map,
    raw_to_norm_map
)
```

3. Implement offset helper:

```text
- find_all_raw_spans(term, raw_text)
- normalize_with_mapping(raw_text)
- recover_raw_span_from_normalized_match()
```

4. Unit test offset:

```text
- raw_text[start:end] == text
- Dính chữ vẫn recover được nếu match raw trực tiếp
- Không sửa raw_text khi output
```

### Deliverable cuối ngày

```text
src/io.py
src/normalization.py
src/offset.py
tests/test_offset.py
```

### Gate

```text
- Có thể đọc 100 file
- Có thể normalize nhưng vẫn trace về raw offset
- Offset validator pass trên 20 case tự tạo
```

---

## Ngày 08/07 — Section/subsection/line inventory

### Công việc

1. Implement section parser:

```text
- Nhận diện main section
- Nhận diện subsection/key-value line
- Nhận diện bullet line
- Gán parent section
```

2. Build `section_aliases.json` v0:

```text
PAST_HISTORY
CURRENT_HISTORY
HOSPITAL_ASSESSMENT
CURRENT_SYMPTOMS
SYMPTOM_DETAIL
PRE_ADMISSION_EVENTS
IMMEDIATE_PRE_ADMISSION_STATUS
LAB_RESULT_SECTION
IMAGING_RESULT_SECTION
PROCEDURE_SECTION
MEDICATION_HISTORY
MEDICATION_ADMINISTERED
```

3. Export section/line inventory:

```text
analysis/section_inventory.csv
analysis/line_inventory.csv
```

4. Review nhanh 20 file:

```text
- Header nào bị miss
- Header nào parse sai
- Section nào overlap sai
```

### Deliverable cuối ngày

```text
src/section_parser.py
data_resources/section_aliases.json
analysis/section_inventory.csv
analysis/line_inventory.csv
tests/test_section_parser.py
```

### Gate

```text
- Parse được section/subsection cho >= 90/100 file
- Không làm hỏng offset raw
- Mỗi line có file_id, section_type, line_start, line_end
```

---

## Ngày 09/07 — Rule extraction V0

### Công việc

Implement extractor cho 5 nhóm.

#### Lab/result extractor

```text
- Tên xét nghiệm + số
- Tên xét nghiệm + dấu : hoặc =
- Kết quả định tính: âm tính, dương tính, bình thường, tăng, giảm, đang chờ
```

Deliverable:

```text
src/extractors/lab_extractor.py
data_resources/lab_seed_terms.csv
```

#### Drug extractor

```text
- Drug dictionary
- Brand/generic alias
- Strength pattern: 10 mg, 0.5mg, 750mg iv, 1 gram
- Route/frequency: po, iv, q6h, bid, daily, prn
```

Deliverable:

```text
src/extractors/drug_extractor.py
data_resources/drug_aliases.csv
data_resources/drug_context_terms.csv
```

#### Diagnosis/symptom dictionary extractor

```text
- diagnosis seed terms
- symptom seed terms
- abbreviation expansion
- section-aware confidence
```

Deliverable:

```text
src/extractors/diagnosis_extractor.py
src/extractors/symptom_extractor.py
data_resources/diagnosis_seed_terms.csv
data_resources/symptom_seed_terms.csv
data_resources/abbreviation_map.csv
```

#### Non-target filter

```text
- imaging/procedure terms không output trực tiếp
- nhưng giữ làm context để tìm finding phía sau
```

Deliverable:

```text
data_resources/non_target_medical_terms.csv
```

### Deliverable cuối ngày

```text
analysis/span_candidates_v0.jsonl
```

### Gate

```text
- Sinh được span candidates cho 100 file
- Không crash
- Mỗi span có start/end/text/type_candidate/source/confidence
- Offset validator pass >= 98% candidates
```

---

## Ngày 10/07 — Assertion, merge, JSON output V0

### Công việc

1. Implement assertion detection:

```text
isNegated:
- không
- không có
- không ghi nhận
- không phát hiện
- không thấy
- phủ nhận
- âm tính

isHistorical:
- tiền sử
- trước đây
- đã từng
- đã sử dụng
- thuốc trước khi nhập viện
- bệnh lý mạn tính

isFamily:
- strict pattern family_member + có/bị/mắc/tiền sử + entity
```

2. Implement assertion scope:

```text
- Trigger ảnh hưởng entity trong cùng câu hoặc cùng bullet
- Dừng tại ".", ";", xuống dòng, "nhưng", "tuy nhiên"
- Không dùng family trigger nếu người nhà chỉ là narrator
```

3. Implement overlap resolver:

Priority:

```text
1. Lab result value
2. Lab name
3. Drug
4. Diagnosis
5. Symptom
```

4. Implement JSON writer:

```text
output/{file_id}.json
```

5. Implement validator:

```text
- schema valid
- type valid
- assertion valid
- candidates field valid
- raw_text[start:end] == text
- no duplicate exact object
```

### Deliverable cuối ngày

```text
src/assertion.py
src/merge.py
src/output_writer.py
src/validator.py
outputs/v0/output/
outputs/v0/output.zip
reports/validation_v0.md
```

### Gate

```text
- Sinh đủ 100 file JSON
- output.zip đúng structure
- Validator pass 100%
- Không có file rỗng do crash
```

---

# P2 — First valid submission  
**Thời gian:** 11/07–13/07  
**Mục tiêu:** Có first submission hợp lệ càng sớm càng tốt, rồi bắt đầu vòng cải thiện.

---

## Ngày 11/07 — Build ICD/RxNorm mapping V0

### ICD-10 mapping

Implement:

```text
- Local ICD dictionary
- Normalize Vietnamese diagnosis term
- Exact match
- Alias/synonym match
- Fuzzy match
- BM25 nếu kịp
```

Output:

```text
CHẨN_ĐOÁN.candidates = [icd_code_1, icd_code_2]
```

Ranking V0:

```text
exact > alias > fuzzy > BM25
```

### RxNorm mapping

Implement:

```text
- Local RxNorm dictionary hoặc curated drug-to-rxcui map
- Brand/generic alias
- Ingredient + strength parser
- Ingredient-only fallback
```

Output:

```text
THUỐC.candidates = [rxcui_1, rxcui_2]
```

### Deliverable cuối ngày

```text
src/linking/icd10_linker.py
src/linking/rxnorm_linker.py
data_resources/icd10_index.*
data_resources/rxnorm_index.*
outputs/v0_linked/output.zip
reports/mapping_coverage_v0.md
```

### Gate

```text
- >= 80% diagnosis spans có candidate hoặc explicit unmapped reason
- >= 90% drug spans có candidate hoặc explicit unmapped reason
- Không có candidate rỗng cho thuốc/chẩn đoán phổ biến
```

---

## Ngày 12/07 — Internal QA và first submission candidate

### Công việc

1. Chạy end-to-end trên toàn bộ 100 file.

2. Tạo reports:

```text
- số entity theo type
- số candidate theo type
- số assertion theo type
- unmapped diagnosis list
- unmapped drug list
- top duplicated spans
- offset failure list
```

3. Manual review 20 file ưu tiên:

```text
- 5 file ngắn
- 5 file dài
- 5 file nhiều thuốc/lab
- 5 file nhiều phủ định
```

4. Sửa lỗi nghiêm trọng:

```text
- JSON schema
- offset
- candidate format
- assertion quá rộng
- duplicate lớn
```

### Deliverable cuối ngày

```text
outputs/submission_01/output.zip
reports/submission_01_QA.md
analysis/error_log_submission_01.csv
```

### Gate trước submission

```text
- Validator pass 100%
- Không crash trên clean input_dir
- Không hard-code all.txt
- output.zip structure đúng
- Có README chạy predict.py
```

---

## Ngày 13/07 — First submission và baseline freeze

### Công việc

1. Submit `outputs/submission_01/output.zip`.

2. Ghi lại:

```text
- thời điểm submit
- config/rule version
- dictionary version
- public score nếu có
- nhận xét lỗi từ leaderboard nếu có
```

3. Freeze baseline:

```text
git tag v0_first_submission
```

4. Tạo baseline comparison file:

```text
reports/submission_history.md
```

### Deliverable cuối ngày

```text
submission_01 đã nộp
git tag v0_first_submission
reports/submission_history.md
```

### Gate

```text
- Có first public score hoặc xác nhận submission hợp lệ
- Có bản baseline có thể rollback
```

---

# P3 — Error analysis và cải thiện V1/V2  
**Thời gian:** 14/07–18/07  
**Mục tiêu:** Dựa trên first submission, cải thiện rõ span boundary, assertion và mapping.

---

## Ngày 14/07 — Error analysis có hệ thống

### Công việc

Tạo bảng lỗi:

```text
analysis/error_log_v1.csv
```

Schema:

```text
file_id
span_text
type_pred
error_category
module
reason
fix_action
priority
```

Error categories:

```text
- missed_span
- wrong_boundary
- wrong_type
- false_positive
- wrong_assertion
- missing_assertion
- wrong_candidate
- missing_candidate
- duplicate
- offset_error
```

Review ít nhất:

```text
- 30 file hoặc 300 span candidates
- toàn bộ unmapped drug
- toàn bộ unmapped diagnosis
- top 50 false-positive-looking terms
```

### Deliverable

```text
analysis/error_log_v1.csv
reports/error_analysis_v1.md
```

---

## Ngày 15/07 — Improve section/line parser + boundary repair

### Công việc

1. Bổ sung section aliases từ lỗi.

2. Thêm boundary repair rules:

```text
- không lấy prefix: "được chẩn đoán", "ghi nhận", "cho thấy"
- không lấy suffix: "không đặc hiệu" nếu không thuộc tên bệnh
- trim punctuation/bullet
- giữ span dài khi symptom có anatomical location
```

3. Fix nested span:

```text
đau bụng
đau bụng vùng hạ sườn phải
```

Rule:

```text
Nếu cùng type overlap và span dài có nghĩa hơn → giữ span dài
```

### Deliverable

```text
outputs/v1_boundary/output.zip
reports/boundary_improvement.md
```

---

## Ngày 16/07 — Improve assertion

### Công việc

1. Fix negation scope:

```text
Không sốt, không ớn lạnh, đau bụng âm ỉ
→ sốt negated, ớn lạnh negated, đau bụng không negated
```

2. Fix historical:

```text
- PAST_HISTORY: strong prior
- MEDICATION_HISTORY: historical for drugs
- PRE_ADMISSION_EVENTS: weak prior, cần trigger cụ thể
```

3. Fix family strict:

```text
Không gắn isFamily cho:
- người nhà kể
- con trai phát hiện
- cháu gái hét lên

Chỉ gắn nếu:
family member + có/bị/mắc/tiền sử + entity
```

### Deliverable

```text
src/assertion.py updated
tests/test_assertion.py
reports/assertion_error_reduction.md
```

---

## Ngày 17/07 — Improve ICD/RxNorm mapping

### ICD

Công việc:

```text
- Bổ sung synonym tiếng Việt
- Bổ sung abbreviation bệnh
- Fix ICD-10 vs ICD-10-CM mismatch nếu phát hiện
- Thêm top-k cap: thường 1–3 candidates
```

### RxNorm

Công việc:

```text
- Bổ sung brand/generic alias
- Parse strength tốt hơn
- Không output drug class chung như kháng sinh
- Fix dính chữ: doxycyclinebactrim, albuterolipratropium
```

### Deliverable

```text
reports/mapping_improvement_v1.md
data_resources/drug_aliases.csv updated
data_resources/diagnosis_synonyms.csv updated
outputs/v1_mapping/output.zip
```

---

## Ngày 18/07 — Submission 02

### Công việc

1. Run full pipeline.

2. QA:

```text
- validator
- type distribution comparison v0 vs v1
- mapping coverage
- assertion count
- duplicate count
```

3. Submit nếu tốt hơn hoặc có confidence cao.

4. Tag:

```text
git tag v1_submission_02
```

### Deliverable

```text
outputs/submission_02/output.zip
reports/submission_02_QA.md
git tag v1_submission_02
```

---

# P4 — Optional model / recall expansion / advanced fallback  
**Thời gian:** 19/07–23/07  
**Mục tiêu:** Tăng recall hoặc mapping nếu baseline đã ổn. Không làm module mới nếu baseline còn lỗi schema/offset.

---

## Ngày 19/07 — Weak label dataset cho NER hoặc reranker

### Công việc

Tạo dữ liệu từ `span_candidates` đã review:

```text
- accepted spans
- rejected spans
- weak labels từ dictionary
- synthetic examples
```

Export:

```text
data_train/ner_weak_train.jsonl
data_train/ner_dev_reviewed.jsonl
```

Nếu không đủ nhãn, không train NER; chuyển sang mở rộng dictionary/rule.

### Deliverable

```text
data_train/ner_weak_train.jsonl
data_train/ner_dev_reviewed.jsonl
reports/weak_label_quality.md
```

---

## Ngày 20/07 — NER experiment hoặc dictionary expansion

### Option A: NER nếu có nhãn đủ

Test nhanh:

```text
- XLM-R-base
- PhoBERT-base
- ViHealthBERT nếu setup thuận lợi
```

Metric nội bộ:

```text
- exact span F1
- boundary error rate
- type confusion
```

### Option B: Không train NER

Mở rộng:

```text
- diagnosis_seed_terms
- symptom_seed_terms
- lab_seed_terms
- abbreviation_map
- noise_normalization
```

### Deliverable

```text
reports/ner_or_dictionary_experiment.md
```

---

## Ngày 21/07 — Integrate optional module có kiểm soát

Nếu NER tốt:

```text
- NER chỉ bổ sung recall
- Rule/dictionary vẫn có priority cho lab/drug
- NER span phải qua validator + overlap resolver
```

Nếu dùng LLM fallback:

```text
- Chỉ cho unmapped/ambiguous
- Chỉ chọn trong candidate list đã có
- Không sinh mã mới ngoài candidate
- Không sửa raw offset
```

### Deliverable

```text
src/extractors/ner_extractor.py optional
src/linking/llm_fallback.py optional
reports/integration_optional_module.md
```

---

## Ngày 22/07 — Ablation test

Chạy các cấu hình:

```text
A: rule/dictionary only
B: A + improved assertion
C: B + improved mapping
D: C + NER/dictionary expansion
E: D + optional fallback
```

So sánh:

```text
- number of spans by type
- mapping coverage
- assertion distribution
- validation error
- manual review score trên subset cố định
```

### Deliverable

```text
reports/ablation_results.md
outputs/ablation_A/
outputs/ablation_B/
outputs/ablation_C/
outputs/ablation_D/
```

---

## Ngày 23/07 — Submission 03

### Công việc

1. Chọn config tốt nhất từ ablation.

2. Run full pipeline.

3. Submit.

4. Tag:

```text
git tag v2_submission_03
```

### Deliverable

```text
outputs/submission_03/output.zip
reports/submission_03_QA.md
git tag v2_submission_03
```

---

# P5 — Stabilization và release candidate  
**Thời gian:** 24/07–27/07  
**Mục tiêu:** Không thêm module lớn. Tập trung giảm lỗi, ổn định, đóng gói.

---

## Ngày 24/07 — Regression test suite

### Công việc

Tạo test cases từ lỗi đã gặp:

```text
tests/fixtures/
├── negation_cases.txt
├── historical_cases.txt
├── family_cases.txt
├── drug_cases.txt
├── lab_cases.txt
├── offset_cases.txt
└── overlap_cases.txt
```

Mỗi bug đã fix phải có test.

### Deliverable

```text
tests/test_regression.py
reports/regression_test_status.md
```

### Gate

```text
pytest pass
validator pass
```

---

## Ngày 25/07 — Packaging dry-run trên clean environment

### Công việc

1. Clone repo vào folder mới.

2. Install từ README.

3. Run:

```bash
python predict.py --input_dir test/input --output_dir output
python make_output_zip.py --output_dir output --zip_path output.zip
```

4. Kiểm tra:

```text
- Không thiếu file resource
- Không phụ thuộc path local
- Không cần notebook
- Không cần API key
- Runtime chấp nhận được
```

### Deliverable

```text
reports/packaging_dry_run.md
README_RUN.md
```

---

## Ngày 26/07 — Release candidate selection

### Công việc

So sánh các submission/config:

```text
submission_01
submission_02
submission_03
local candidate current
```

Chọn release candidate dựa trên:

```text
- public score nếu có
- manual review
- stability
- mapping coverage
- ít false positive hơn
```

Không nhất thiết chọn bản có nhiều span nhất.

### Deliverable

```text
outputs/release_candidate/output.zip
configs/final_config.yaml
reports/release_candidate_decision.md
git tag release_candidate
```

---

## Ngày 27/07 — Final improvement nhỏ

Chỉ sửa lỗi nhỏ:

```text
- thêm alias chắc chắn
- sửa candidate mapping chắc chắn
- sửa offset/trim
- giảm duplicate
```

Không làm:

```text
- train model mới lớn
- đổi architecture
- thêm fallback chưa test
```

### Deliverable

```text
outputs/release_candidate_2/output.zip
reports/final_small_fixes.md
```

---

# P6 — Final submission và source package  
**Thời gian:** 28/07–30/07  
**Mục tiêu:** Final output + source code package dựng lại được.

---

## Ngày 28/07 — Final QA

### Checklist

```text
- output.zip đúng structure
- đủ 100 json
- JSON parse 100/100
- offset valid 100%
- type valid 100%
- assertion valid 100%
- candidates valid
- không có debug field
- không có absolute local path
- không có hard-code public file names ngoài logic đọc input_dir
```

### Deliverable

```text
outputs/final_candidate/output.zip
reports/final_QA.md
```

---

## Ngày 29/07 — Final submission + source packaging

### Công việc

1. Submit final output.

2. Tạo source package:

```text
source_package/
├── README_RUN.md
├── requirements.txt
├── predict.py
├── make_output_zip.py
├── src/
├── configs/
├── data_resources/
├── model_weights/      # nếu có
└── tests/
```

3. Viết README:

```text
- Python version
- Cài đặt dependencies
- Cách build resources nếu cần
- Cách chạy inference
- Cách tạo output.zip
- Expected runtime
- Hardware requirement
```

4. Dry-run source package lần cuối.

### Deliverable

```text
final_output.zip
source_code.zip
README_RUN.md
reports/source_package_dry_run.md
git tag final_submission
```

---

## Ngày 30/07 — Buffer và contingency

Không lên kế hoạch việc lớn trong ngày cuối.

Chỉ làm:

```text
- submit lại nếu file lỗi
- sửa packaging nếu BTC yêu cầu
- kiểm tra checksum/file size
- backup output/source
- ghi lại final version
```

### Deliverable cuối cùng

```text
final/
├── output.zip
├── source_code.zip
├── README_RUN.md
├── final_config.yaml
└── final_submission_notes.md
```

---

## 5. Branching và version control

Khuyến nghị branch:

```text
main
dev
feature/section-parser
feature/extractors
feature/linking
feature/assertion
feature/validator
experiment/ner
experiment/llm-fallback
```

Tag bắt buộc:

```text
v0_first_submission
v1_submission_02
v2_submission_03
release_candidate
final_submission
```

Mỗi submission phải ghi lại:

```text
- git commit hash
- config file
- dictionary version
- output.zip path
- public score nếu có
- ghi chú thay đổi
```

File:

```text
reports/submission_history.md
```

Template:

```markdown
## Submission 02 — 18/07

- Commit:
- Config:
- Output:
- Public score:
- Main changes:
- Known risks:
- Next actions:
```

---

## 6. Test plan chi tiết

## 6.1. Unit tests

| Module | Test bắt buộc |
|---|---|
| Input loader | đọc đủ file, sort đúng 1–100 |
| Normalization | không làm mất offset |
| Offset | raw_text[start:end] == text |
| Section parser | parse alias, typo header, no-number header |
| Lab extractor | test + value, qualitative result |
| Drug extractor | brand, generic, strength, route |
| Diagnosis extractor | seed/fuzzy/section-aware |
| Symptom extractor | short symptom, long symptom |
| Assertion | negated, historical, family strict |
| Linker | exact/fuzzy/top-k cap |
| Merge | overlap same type, overlap different type |
| Writer | JSON schema |
| Zip builder | đúng folder output/ |

---

## 6.2. Integration tests

Test trên 5 nhóm file:

```text
- short_cases: file ngắn, ít entity
- long_cases: file dài, nhiều section
- lab_heavy_cases
- drug_heavy_cases
- negation_heavy_cases
```

Mỗi integration test kiểm:

```text
- không crash
- output JSON valid
- số span không bất thường
- offset valid
- candidates không sai format
```

---

## 6.3. Regression tests

Mỗi lỗi từng xuất hiện phải thêm fixture.

Ví dụ:

```text
Không sốt, không ớn lạnh, đau bụng âm ỉ
→ sốt isNegated
→ ớn lạnh isNegated
→ đau bụng không isNegated
```

```text
người nhà nhận thấy bệnh nhân mất định hướng
→ không gắn isFamily
```

```text
doxycyclinebactrim
→ tách được doxycycline và bactrim nếu có trong dictionary
```

---

## 6.4. Validator tests

Validator phải fail nếu:

```text
- position sai
- type không hợp lệ
- assertion không hợp lệ
- candidates không phải list
- candidates xuất hiện dạng string
- JSON không parse được
- duplicate exact object
```

Validator phải warning nếu:

```text
- CHẨN_ĐOÁN/THUỐC không có candidates
- quá nhiều candidates cho một span
- quá nhiều span trùng nhau
- file output có số entity quá thấp/cao bất thường
```

---

## 7. Integration plan

## 7.1. Module interface chuẩn

Mọi extractor trả về `SpanCandidate`:

```python
@dataclass
class SpanCandidate:
    file_id: str
    text: str
    start: int
    end: int
    type_candidate: str
    source: list[str]
    confidence: float
    section_type: str | None = None
    subsection_type: str | None = None
    line_text: str | None = None
    left_context: str | None = None
    right_context: str | None = None
    assertion_candidates: list[str] = field(default_factory=list)
    mapping_candidates: list[str] = field(default_factory=list)
    should_output: bool = True
    reject_reason: str | None = None
```

Final writer convert sang schema submit:

```python
{
    "text": span.text,
    "type": span.type_candidate,
    "position": [span.start, span.end],
    "assertions": span.assertion_candidates,
    "candidates": span.mapping_candidates
}
```

---

## 7.2. Pipeline orchestration

```text
load_documents()
→ normalize_documents()
→ parse_sections()
→ build_line_inventory()
→ run_extractors()
→ add_assertions()
→ link_candidates()
→ resolve_overlaps()
→ validate_spans()
→ write_json()
→ validate_outputs()
→ zip_outputs()
```

---

## 7.3. Integration gates

Không merge module nếu:

```text
- làm giảm validator pass rate
- phá offset
- tăng duplicate quá nhiều
- thêm dependency khó cài
- làm runtime tăng mạnh nhưng không có lợi rõ
```

---

## 8. Submission plan

## 8.1. Submission 01 — First valid baseline

Thời gian mục tiêu:

```text
13/07
```

Mục tiêu:

```text
- Có output hợp lệ
- Validator pass
- Mapping V0 có candidates
- Chấp nhận recall chưa cao
```

Không cần:

```text
- NER
- dense retrieval
- LLM fallback
```

---

## 8.2. Submission 02 — Error analysis improvement

Thời gian mục tiêu:

```text
18/07
```

Mục tiêu:

```text
- Fix boundary
- Fix assertion
- Improve ICD/RxNorm mapping
- Giảm false positives
```

---

## 8.3. Submission 03 — Optional model/fallback

Thời gian mục tiêu:

```text
23/07
```

Mục tiêu:

```text
- Add NER/dictionary expansion nếu có lợi
- Add optional fallback nếu ổn định
- Chọn config tốt qua ablation
```

---

## 8.4. Final submission

Thời gian mục tiêu:

```text
29/07
```

Mục tiêu:

```text
- Không còn lỗi schema/offset
- Chọn release candidate ổn định nhất
- Source package chạy lại được
```

---

## 9. Risk register

| Risk | Tác động | Giảm thiểu |
|---|---|---|
| Sai offset | Submission mất điểm nặng | raw_text immutable + validator bắt buộc |
| Sai schema JSON | Submission fail | schema validator + integration test |
| Hard-code public test | Bị loại khi private test | predict.py đọc input_dir tổng quát |
| LLM sinh mã sai | Candidate score giảm | chỉ chọn từ candidate list |
| Quá nhiều false positive | text_score giảm | non-target list + confidence threshold |
| Gán isHistorical quá rộng | assertion_score giảm | time_context + trigger cụ thể |
| Gán isFamily sai | assertion_score giảm | strict family pattern |
| RxNorm thiếu map | candidate_score giảm | brand/generic alias + ingredient fallback |
| ICD quá nhiều candidates | Jaccard giảm | top-k cap 1–3 |
| Module optional phá baseline | mất stability | ablation + rollback tag |
| Không đóng gói được source | rủi ro bị loại | dry-run clean environment từ 25/07 |

---

## 10. Definition of Done

## 10.1. Done cho baseline V0

```text
- Chạy end-to-end trên 100 file
- Sinh đủ 100 JSON
- output.zip đúng format
- Validator pass 100%
- Có candidates cho phần lớn CHẨN_ĐOÁN/THUỐC
- Có report validation
```

## 10.2. Done cho first submission

```text
- Đã submit output.zip
- Có score hoặc xác nhận submission hợp lệ
- Có git tag
- Có submission_history.md
- Có baseline để rollback
```

## 10.3. Done cho release candidate

```text
- Chọn config final
- Regression tests pass
- Dry-run clean environment pass
- Không thêm module lớn nữa
```

## 10.4. Done cho final

```text
- Final output.zip đã nộp
- Source code package đầy đủ
- README_RUN.md rõ ràng
- predict.py chạy lại được trên input_dir mới
- Không phụ thuộc API ngoài
- Tất cả resource/model cần thiết đã đi kèm
```

---

## 11. Checklist hằng ngày

Cuối mỗi ngày cần cập nhật:

```text
- Hôm nay đã hoàn thành gì?
- Deliverable nào được tạo?
- Test nào pass/fail?
- Lỗi lớn nhất hiện tại là gì?
- Ngày mai ưu tiên gì?
- Có cần rollback module nào không?
```

File:

```text
reports/daily_log.md
```

Template:

```markdown
# Daily Log — DD/07

## Done
- ...

## Tests
- ...

## Issues
- ...

## Decisions
- ...

## Next
- ...
```

---

## 12. Kết luận

Kế hoạch triển khai trong cuộc thi nên đi theo nguyên tắc:

```text
Submission hợp lệ sớm
→ error analysis có hệ thống
→ cải thiện từng module có kiểm soát
→ không phá baseline
→ freeze sớm
→ đóng gói source chắc chắn
```

Mốc quan trọng nhất là:

```text
13/07: first valid submission
18/07: improved submission
23/07: optional-module submission
27/07: release candidate
29/07: final submission + source package
30/07: buffer
```

Nếu bị chậm tiến độ, ưu tiên tuyệt đối:

```text
1. output.zip valid
2. offset/schema validator
3. ICD/RxNorm mapping cơ bản
4. assertion rule cơ bản
5. cải thiện dictionary/rule
```

Không hy sinh stability để thêm model phức tạp vào sát hạn.
