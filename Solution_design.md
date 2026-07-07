# Kế hoạch solution, dữ liệu và triển khai dự án - Phiên bản v2

**Bài toán:** Trích xuất, chuẩn hóa và suy luận ngữ cảnh khái niệm y tế từ văn bản lâm sàng tiếng Việt tự do  
**Nguồn dữ liệu quan sát:** `ABOUT.md`, `all.txt` gồm 100 record đã gộp, `data_assessment.md`, và bản kế hoạch tổng quát trước đó `documents.md`  
**Mục tiêu của tài liệu:** Làm lại blueprint triển khai solution theo hướng đúng hơn với toàn bộ 100 file thực tế, thay thế các giả định còn dựa trên 10 sample ban đầu.

---

## 1. Tóm tắt định hướng

Solution nên đi theo hướng **rule-heavy hybrid pipeline**, không dùng LLM end-to-end.

Lý do:

- Output yêu cầu **span text + offset chính xác**; LLM dễ sai vị trí ký tự.
- Mapping `CHẨN_ĐOÁN -> ICD-10` và `THUỐC -> RxNorm` cần kiểm soát candidate, không nên để model sinh mã tự do.
- Dữ liệu 100 file có cấu trúc bán chuẩn: section, subsection, bullet list, key-value line, lab/result pattern và medication pattern khá rõ.
- Dữ liệu cũng nhiều nhiễu: dính chữ, typo, lặp header, lẫn tiếng Anh/viết tắt, phủ định kéo dài, và section không đồng nhất.
- Hackathon cần một hệ thống chạy ổn định, dễ debug, dễ reproduce trên private test.

Pipeline tổng quát:

```text
Raw clinical text
  -> record parser
  -> preprocessing + offset mapping
  -> section/subsection/line detection
  -> span candidate extraction
      - lab/result regex
      - drug dictionary + dose parser
      - diagnosis/symptom dictionary + optional NER
      - abbreviation expansion
  -> assertion detection
  -> ICD/RxNorm candidate generation
  -> candidate reranking
  -> overlap resolution
  -> JSON schema + offset validation
  -> output.zip
```

Nguyên tắc quan trọng nhất: **baseline rule/dictionary chạy chắc trước**, sau đó mới thêm NER, dense retrieval hoặc LLM fallback.

---

## 2. Diễn giải bài toán và metric

### 2.1. Output cần tạo

Mỗi input `.txt` cần xuất một file `.json` tương ứng. Mỗi item trong JSON là một khái niệm y tế có các trường chính:

```json
{
  "text": "...",
  "position": [start, end],
  "type": "TRIỆU_CHỨNG | TÊN_XÉT_NGHIỆM | KẾT_QUẢ_XÉT_NGHIỆM | CHẨN_ĐOÁN | THUỐC",
  "assertions": ["isNegated", "isHistorical", "isFamily"],
  "candidates": ["..."]
}
```

Quy ước nên áp dụng:

- `text`, `position`, `type`, `assertions` nên có cho mọi entity.
- `candidates` bắt buộc có ý nghĩa với `CHẨN_ĐOÁN` và `THUỐC`.
- Với `TRIỆU_CHỨNG`, `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM`, có thể để `candidates: []` hoặc không xuất trường này tùy checker. Khuyến nghị dùng một style thống nhất sau khi test format.
- `position` phải tính trên `raw_text` gốc, không tính trên text đã normalize.
- Validator bắt buộc:

```python
raw_text[start:end] == item["text"]
```

### 2.2. Metric và ưu tiên tối ưu

Metric chính:

```text
final_score = 0.3 * text_score
            + 0.3 * assertions_score
            + 0.4 * candidates_score
```

Hàm ý triển khai:

1. **Candidate mapping quan trọng nhất** vì chiếm 40%.
2. **Span boundary và text chính xác** rất quan trọng vì WER trên text chiếm 30%.
3. **Assertion** cũng chiếm 30%, cần tránh rule quá rộng gây false positive.
4. Sai type bị phạt mạnh vì cùng một span nhưng sai loại sẽ tạo mismatch hai chiều.

Ưu tiên MVP:

```text
1. Output JSON hợp lệ và offset đúng.
2. Bắt chắc lab/result, drug, diagnosis/symptom phổ biến.
3. Mapping RxNorm/ICD bằng exact/fuzzy/BM25.
4. Assertion rule-based có scope kiểm soát.
5. Giảm false positive bằng non-target/auxiliary list.
```

---

## 3. Đặc điểm dữ liệu thực tế từ 100 file

### 3.1. Cấu trúc tổng quan

Dữ liệu là clinical note tiếng Việt bán cấu trúc, thường có 3 khối lớn:

```text
1. Tiền sử bệnh / Tiền sử bệnh nội khoa
2. Tiền sử bệnh hiện tại / Bệnh sử hiện tại / Lịch sử bệnh hiện tại / Bệnh sử
3. Đánh giá tại bệnh viện / Kết quả khám tại bệnh viện / Khám tại bệnh viện
```

Bên trong có nhiều subsection hoặc key-value line:

```text
Lý do nhập viện: ...
Triệu chứng hiện tại
Triệu chứng khi nhập viện
Đặc điểm triệu chứng
Các sự kiện trước khi nhập viện
Tình trạng ngay trước khi nhập viện
Kết quả xét nghiệm
Kết quả phòng thí nghiệm
Kết quả laboratory
Kết quả chẩn đoán hình ảnh
Kết quả hình ảnh
Kết quả chụp ảnh
Các thủ thuật đã thực hiện
Các thuốc đã thực hiện
Các phát hiện chẩn đoán khác
```

### 3.2. Nhiễu thường gặp

Cần xem đây là dữ liệu noisy clinical text, không phải văn bản chuẩn.

Các nhóm nhiễu:

```text
- Dính chữ: atenololtrong, cảm giáckhó chịu, doxycyclinebactrim
- Lặp từ/header: bình thườngbình thường, Kết quả xét nghiệm xét nghiệm
- Lỗi chính tả: hin tại, nhaoaj viện, Kêt quả, sau khí, cơni
- Lẫn tiếng Anh: lower abdominal pain, fever, daily, po, iv, prn
- Viết tắt: CT, MRI, UA, CBC, DVT, AH, LLQ, PICC, ERCP
- Placeholder: [Date], DD MM, ngày w
- Section không đánh số hoặc thiếu section
- Bullet list và paragraph tự do xen lẫn
```

### 3.3. Các rủi ro chính khi trích xuất

| Rủi ro | Ví dụ | Hướng xử lý |
|---|---|---|
| Sai offset do normalize | dính chữ, dư whitespace | giữ raw text, tạo offset mapper, validate cuối |
| Sai type giữa symptom/diagnosis | `đau bụng` vs `viêm túi mật cấp` | dùng section + dictionary + context |
| Output nhầm procedure/imaging | `chụp CT`, `siêu âm`, `ERCP` | auxiliary/non-target list |
| Lab section chứa diagnosis/finding | ECG cho thấy nhồi máu cơ tim cũ | không ép toàn bộ lab section thành lab |
| Drug context bị output như thuốc | `kháng sinh`, `liệu pháp lợi tiểu` | tách drug context khỏi drug seed |
| Gán historical quá rộng | pre-admission events có triệu chứng hiện tại | dùng time_context + trigger cụ thể |
| Gán family sai | người nhà kể chuyện | family rule phải strict |
| Candidate quá nhiều | ICD/RxNorm ambiguous | rerank + giới hạn top-k theo confidence |

---

## 4. Nguyên tắc thiết kế solution

### 4.1. Không dùng LLM end-to-end

LLM chỉ nên dùng ở các vai trò có kiểm soát:

```text
- verify/rerank trong candidate list đã generate sẵn
- hỗ trợ case ambiguous
- hỗ trợ phân biệt span dài/ngắn khi rule không chắc
```

Không nên để LLM:

```text
- sinh offset trực tiếp
- sinh mã ICD/RxNorm ngoài candidate index
- tự quyết định toàn bộ JSON
- gọi API ngoài nếu luật thi cấm hoặc runtime private test không có internet
```

### 4.2. Mọi module phải deterministic ở bản MVP

MVP nên có đặc tính:

```text
- chạy offline
- không phụ thuộc API ngoài
- dễ debug từng file
- có log trung gian
- có validator bắt lỗi trước khi zip
- không hard-code theo 100 public files
```

### 4.3. Tách raw và normalized text

Luôn giữ hai bản:

```text
raw_text        : dùng để trả text và position
normalized_text : dùng để lowercase, fuzzy, regex, dictionary matching
```

Khi match trên normalized text, phải ánh xạ được về raw span.

### 4.4. `span_candidates` là nguồn sự thật trung gian

Không maintain nhiều list thủ công song song. Quy trình đúng:

```text
100 raw files
  -> section/line inventory
  -> span_candidates.jsonl
  -> review/clean
  -> derive dictionaries/rules
  -> build final extractor
```

Seed dictionaries nên được sinh/chuẩn hóa từ `span_candidates` đã review, không chỉ lấy từ 10 sample ban đầu.

---

## 5. Data assessment layer

Phần này phải bám theo `Data_assessment.md` và là bước bắt buộc trước khi tối ưu model.

### 5.1. Đầu ra bắt buộc

Data assessment cần tạo 5 nhóm artifact:

```text
1. record_inventory.csv
2. section_inventory.jsonl
3. line_inventory.jsonl
4. span_candidates.jsonl
5. derived dictionaries/configs
```

Derived dictionaries/configs gồm:

```text
- section_aliases.json
- diagnosis_seed_terms.csv
- symptom_seed_terms.csv
- drug_seed_terms.csv
- drug_context_terms.csv
- lab_seed_terms.csv
- assertion_triggers.json
- abbreviation_map.csv
- noise_normalization.json
- non_target_medical_terms.csv
```

### 5.2. Record inventory

Mỗi record cần có metadata:

```json
{
  "file_id": "1.txt",
  "record_index": 1,
  "char_len": 2345,
  "line_count": 87,
  "has_numbered_sections": true,
  "detected_main_sections": ["PAST_HISTORY", "CURRENT_HISTORY", "HOSPITAL_ASSESSMENT"],
  "notes": []
}
```

Mục tiêu:

- xác nhận đủ 100 record;
- phát hiện record quá ngắn/quá dài;
- phát hiện record thiếu section;
- phục vụ sampling khi review lỗi.

### 5.3. Section/subsection inventory

Schema đề xuất:

```json
{
  "file_id": "1.txt",
  "section_text": "Tiền sử bệnh hiện tại",
  "section_type": "CURRENT_HISTORY",
  "parent_section_type": null,
  "level": 1,
  "start": 523,
  "end": 545,
  "line_id": 15,
  "confidence": 0.98,
  "alias_source": "section_aliases.json"
}
```

Cần phân biệt:

```text
main section       : Tiền sử bệnh, Bệnh sử hiện tại, Đánh giá tại bệnh viện
subsection         : Triệu chứng hiện tại, Kết quả xét nghiệm, Thuốc trước nhập viện
field/key-value    : Lý do nhập viện: ..., Thời điểm khởi phát: ...
```

### 5.4. Section aliases v2

Alias cần rộng hơn bản cũ.

```json
{
  "PAST_HISTORY": [
    "tiền sử bệnh",
    "tiền sử bệnh nội khoa",
    "các bệnh mãn tính",
    "các bệnh lý mạn tính",
    "bệnh mãn tính",
    "bệnh lý mãn tính",
    "bệnh lý mạn tính",
    "tiền sử phẫu thuật",
    "tiền sử phẫu thuật / thủ thuật"
  ],
  "CURRENT_HISTORY": [
    "tiền sử bệnh hiện tại",
    "bệnh sử hiện tại",
    "bệnh sử  hiện tại",
    "lịch sử bệnh hiện tại",
    "bệnh sử",
    "bệnh sử hin tại",
    "bệnh sử  hin tại",
    "tiền sử bệnh bệnh hiện tại"
  ],
  "HOSPITAL_ASSESSMENT": [
    "đánh giá tại bệnh viện",
    "kết quả khám tại bệnh viện",
    "khám tại bệnh viện",
    "khám  tại bệnh viện",
    "đánh giá tại bệnh viện",
    "cận lâm sàng"
  ],
  "CURRENT_SYMPTOMS": [
    "triệu chứng hiện tại",
    "các triệu chứng hiện tại",
    "triệu chứng khi nhập viện",
    "triệu chứng chính",
    "dấu hiệu lâm sàng"
  ],
  "SYMPTOM_DETAIL": [
    "đặc điểm triệu chứng",
    "đặc điểm của triệu chứng",
    "diễn biến bệnh"
  ],
  "PRE_ADMISSION_EVENTS": [
    "các sự kiện trước khi nhập viện",
    "sự kiện trước khi nhập viện",
    "các diễn biến trước khi nhập viện",
    "diễn biến trước khi nhập viện",
    "các biến trước khi nhập viện"
  ],
  "IMMEDIATE_PRE_ADMISSION_STATUS": [
    "tình trạng ngay trước khi nhập viện",
    "tình trạng trước nhập viện",
    "tình trạng lúc vào viện"
  ],
  "LAB_RESULT_SECTION": [
    "kết quả xét nghiệm",
    "kết quả xét nghiệm máu",
    "kết quả phòng thí nghiệm",
    "kết quả laboratory",
    "xét nghiệm"
  ],
  "IMAGING_RESULT_SECTION": [
    "kết quả chẩn đoán hình ảnh",
    "kết quả hình ảnh",
    "kết quả chụp ảnh",
    "kết quả chụp ảnh/kỹ thuật chẩn đoán hình ảnh",
    "chẩn đoán hình ảnh và thăm dò"
  ],
  "PROCEDURE_SECTION": [
    "các thủ thuật đã thực hiện",
    "thủ thuật đã thực hiện",
    "thủ thuật thực hiện",
    "các thủ thuật thực hiện"
  ],
  "MEDICATION_HISTORY": [
    "thuốc trước khi nhập viện",
    "thuốc trước khi nhập viện lần này",
    "thuốc đã dùng trước đây",
    "bệnh nhân có tiền sử dụng thuốc"
  ],
  "MEDICATION_ADMINISTERED": [
    "các thuốc đã thực hiện",
    "được cho dùng",
    "được chỉ định điều trị",
    "dùng tại khoa cấp cứu"
  ]
}
```

### 5.5. Line inventory

Line-level table giúp debug và rule extraction.

```json
{
  "file_id": "33.txt",
  "line_id": 42,
  "line_text": "- được cho levofloxacin 750mg iv",
  "line_start": 1830,
  "line_end": 1870,
  "section_type": "HOSPITAL_ASSESSMENT",
  "subsection_type": "MEDICATION_ADMINISTERED",
  "line_kind": "bullet",
  "key": null,
  "value": null
}
```

`line_kind` nên có:

```text
header
subheader
key_value
bullet
free_text
continuation
```

### 5.6. Span candidates

Schema trung gian chính:

```json
{
  "file_id": "66.txt",
  "text": "tăng huyết áp",
  "start": 95,
  "end": 108,
  "type_candidate": "CHẨN_ĐOÁN",
  "section_type": "PAST_HISTORY",
  "subsection_type": "CHRONIC_DISEASES",
  "line_id": 7,
  "line_text": "- tăng huyết áp",
  "left_context": "",
  "right_context": "",
  "time_context": "past",
  "source": ["dictionary", "section_rule"],
  "confidence": 0.92,
  "assertion_candidates": ["isHistorical"],
  "mapping_candidates": [],
  "should_output": true,
  "span_status": "candidate",
  "reject_reason": null,
  "notes": ""
}
```

Bổ sung bắt buộc so với bản cũ:

```text
- time_context
- span_status
- reject_reason
- subsection_type
- source list
- mapping_candidates
```

`span_status`:

```text
candidate | accepted | rejected | needs_review
```

`reject_reason` ví dụ:

```text
procedure_or_imaging_method
non_specific_drug_context
family_narrator_not_family_history
lab_section_but_diagnosis_finding
bad_offset
duplicate_overlap
```

---

## 6. Module preprocessing và offset mapping

### 6.1. Raw text không được sửa

Không được normalize trực tiếp lên raw text dùng cho output.

Các thao tác chỉ thực hiện trên `normalized_text`:

```text
- Unicode normalize
- lowercase
- collapse whitespace
- chuẩn hóa dash/hyphen
- chuẩn hóa dấu ngoặc
- chuẩn hóa tiếng Việt không dấu cho fuzzy
- sửa typo phục vụ matching
```

### 6.2. Offset mapping

Nếu normalize thay đổi chiều dài chuỗi, cần offset map:

```python
normalized_char_index -> raw_char_index
```

Cách thực dụng cho MVP:

- Ưu tiên match trực tiếp trên raw text với regex case-insensitive.
- Với dictionary fuzzy, sau khi tìm normalized match, dùng search gần nhất trong raw line/window để recover span.
- Luôn validate cuối bằng exact substring.

### 6.3. Normalization resources

`noise_normalization.json` chỉ dùng cho matching:

```json
{
  "hin tại": "hiện tại",
  "Kêt quả": "Kết quả",
  "nhaoaj viện": "nhập viện",
  "sau khí": "sau khi",
  "cơni": "cơn",
  "morphineiv morphine": "morphine",
  "atenololtrong": "atenolol trong",
  "doxycyclinebactrim": "doxycycline bactrim"
}
```

---

## 7. Span extraction theo entity type

## 7.1. `TÊN_XÉT_NGHIỆM` và `KẾT_QUẢ_XÉT_NGHIỆM`

### Hướng chính

Dùng regex + lab dictionary.

Pattern phổ biến:

```text
TEST_NAME VALUE
TEST_NAME: VALUE
TEST_NAME là VALUE
TEST_NAME tăng/giảm/bình thường/âm tính/dương tính/đang chờ
```

Regex gợi ý:

```regex
(?P<test>[A-Za-zÀ-ỹ0-9%\-\(\)\/\s]{2,80})\s*(?:[:=]|là)?\s*(?P<value>[<>]?\d+[,.]?\d*|âm tính|dương tính|bình thường|tăng nhẹ|đang chờ)
```

Cần dùng dictionary để giới hạn `test`, tránh bắt nhầm cả câu.

### Lab dictionary

Nguồn ban đầu:

```text
wbc, bạch cầu, neutrophil, lymphocyte, hct, hematocrit,
platelets, tiểu cầu, hco3-, bicarbonate, ag, anion gap,
bun, creatinine, glucose, đường huyết, lactate, acid lactat,
ua, urinalysis, cbc, công thức máu, ck, alt, ast, bilirubin,
troponin, hiv vl, soi tươi ký sinh trùng, cấy máu
```

### Cảnh báo quan trọng

Không ép toàn bộ `LAB_RESULT_SECTION` thành lab. Trong section xét nghiệm có thể có disease/finding:

```text
- rung nhĩ kèm đáp ứng thất nhanh
- nhồi máu cơ tim vùng dưới cũ
- thay đổi sóng T không đặc hiệu
- suy thận cấp
- bất thường điện giải
```

Rule:

```text
Nếu pattern test + value/qualifier rõ -> lab name + lab result.
Nếu phrase giống diagnosis/finding -> chuyển sang diagnosis detector.
Nếu phrase là procedure/imaging method -> non-target/context.
```

---

## 7.2. `THUỐC`

### Hướng chính

Dùng:

```text
drug dictionary
+ brand/generic alias
+ dose/strength/route parser
+ RxNorm local lookup
```

### Drug span parser

Pattern thuốc thường gồm:

```text
ingredient/brand + strength + unit + route + frequency
```

Ví dụ:

```text
metoprolol 25mg po bid
aspirin 325mg
levofloxacin 750mg iv
insulin glargine
albuterolipratropium nebulizer
```

Các thành phần cần parse:

```text
drug_name
strength
unit
route
frequency
form
prn flag
```

### Tách drug seed và drug context

Không đưa từ chung chung như `kháng sinh` vào `drug_seed_terms.csv`.

`drug_seed_terms.csv` chỉ gồm thuốc cụ thể có thể map RxNorm:

```text
metoprolol
aspirin
omeprazole
vancomycin
levofloxacin
bactrim
cipro
seroquel
morphine
toradol
tylenol
advil
torsemide
insulin glargine
rosuvastatin
carvedilol
warfarin
coumadin
eliquis
furosemide
bumetanide
methylprednisolone
```

`drug_context_terms.csv` dùng làm trigger, không output mặc định:

```text
kháng sinh
kháng sinh tĩnh mạch
thuốc giảm đau
thuốc giảm đau opioid
liệu pháp lợi tiểu
chống đông máu
được cho dùng
được chỉ định điều trị
điều trị bằng
đã hết thuốc
đã ngừng sử dụng
```

### Medication context

Cần tách:

```text
MEDICATION_HISTORY       -> thường isHistorical cho thuốc
MEDICATION_ADMINISTERED  -> không mặc định isHistorical
```

Ví dụ:

```text
Thuốc trước khi nhập viện: aspirin 325mg hằng ngày
  -> aspirin likely isHistorical

Các thuốc đã thực hiện: vancomycin 1 gram
  -> vancomycin là thuốc được dùng tại viện, không gắn isHistorical mặc định
```

---

## 7.3. `CHẨN_ĐOÁN`

### Hướng MVP

Dùng:

```text
diagnosis dictionary
+ ICD synonym dictionary
+ fuzzy matching
+ section-aware confidence
+ imaging/finding extraction rules
```

Các vùng ưu tiên:

```text
PAST_HISTORY / CHRONIC_DISEASES
ADMISSION_REASON
HOSPITAL_ASSESSMENT
IMAGING_RESULT_SECTION findings
LAB_RESULT_SECTION diagnostic findings
DIAGNOSTIC_FINDINGS
PRE_ADMISSION_EVENTS với trigger chẩn đoán
```

### Không nhầm procedure/imaging method

Không output:

```text
chụp CT
MRI
siêu âm
chụp x-quang
ERCP
chọc hút bằng kim nhỏ
chọc dò dịch não tủy
stent
lấy mẫu cấy máu
```

Nhưng phải output finding phía sau nếu là bệnh/chẩn đoán:

```text
chụp CT cho thấy viêm túi mật thủng cấp tính
  -> không output "chụp CT"
  -> output "viêm túi mật thủng cấp tính"
```

### Optional NER

NER chỉ nên thêm sau khi có:

```text
- rule baseline chạy được
- span_candidates đã review một phần
- weak/synthetic/manual labels đủ dùng
```

Không nên fine-tune NER nếu chưa có label rõ ràng.

---

## 7.4. `TRIỆU_CHỨNG`

### Hướng chính

Dùng dictionary + context + optional NER.

Vùng ưu tiên:

```text
Lý do nhập viện
Triệu chứng hiện tại
Triệu chứng khi nhập viện
Đặc điểm triệu chứng
Diễn biến bệnh
Tình trạng ngay trước khi nhập viện
```

Ví dụ span:

```text
khó thở
đau ngực
đau bụng vùng hạ sườn phải
buồn nôn
sốt
chóng mặt
ngất xỉu
ho ra máu
mệt mỏi
phù ngoại vi
```

### Boundary policy

Cần nhất quán giữa span ngắn và span dài:

```text
đau bụng
đau bụng vùng hạ sườn phải
đau âm ỉ vùng quanh rốn
khó thở
khó thở khi gắng sức
```

Khuyến nghị:

- Nếu cụm vị trí/tính chất là một phần tự nhiên của triệu chứng, giữ span dài.
- Không lấy cả câu mô tả dài nếu có thể cắt thành cụm triệu chứng rõ.
- Với lặp lại cùng symptom ở nhiều vị trí, giữ từng occurrence nếu output yêu cầu theo span trong text.

---

## 8. Assertion detection

### 8.1. Scope assertion

Assertion chỉ áp dụng cho:

```text
CHẨN_ĐOÁN
THUỐC
TRIỆU_CHỨNG
```

Không cần assertion cho:

```text
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
```

Nếu vẫn để `assertions: []` cho lab/result thì hợp lệ.

### 8.2. `isNegated`

Trigger:

```text
không
không có
không ghi nhận
không phát hiện
không thấy
chưa
phủ nhận
loại trừ
âm tính
```

Scope rule MVP:

```text
Trigger ảnh hưởng entity sau nó cho tới:
- dấu chấm
- dấu chấm phẩy
- xuống dòng
- từ nối đối lập: nhưng, tuy nhiên, song
```

Cần xử lý list phủ định:

```text
Không sốt, ớn lạnh, nôn, táo bón, ho hoặc tiểu khó
```

Trong câu trên, toàn bộ các symptom trong list đều có thể `isNegated`.

### 8.3. `isHistorical`

Không gán cứng chỉ vì nằm trong `PRE_ADMISSION_EVENTS`.

Prior theo section:

```text
PAST_HISTORY              -> strong historical prior
MEDICATION_HISTORY        -> strong historical prior cho thuốc
CHRONIC_DISEASES          -> strong historical prior cho diagnosis
PRE_ADMISSION_EVENTS      -> weak historical prior
CURRENT_HISTORY           -> current by default
HOSPITAL_ASSESSMENT       -> current/in-hospital by default
```

Trigger:

```text
tiền sử
trước đây
đã từng
từng bị
mạn tính
đã điều trị
đã sử dụng
thuốc trước khi nhập viện
đã ngừng
đã hết thuốc
gần đây nhập viện vì
xuất viện về nhà
```

Nên thêm `time_context` để hỗ trợ quyết định:

```text
past | recent_past | current | in_hospital | unknown
```

### 8.4. `isFamily`

Trigger family phải rất strict.

Không gắn `isFamily` chỉ vì có:

```text
người nhà kể
con trai phát hiện
cháu gái hét lên
gia đình lo ngại
```

Chỉ gắn khi pattern thể hiện bệnh/triệu chứng thuộc người nhà:

```text
family_member + có/bị/mắc/tiền sử/chẩn đoán + disease_or_symptom
```

Ví dụ đúng:

```text
bố bệnh nhân có tiền sử hen
mẹ bệnh nhân bị đái tháo đường
nhiều người trong gia đình có triệu chứng tương tự
```

---

## 9. ICD-10 và RxNorm mapping

## 9.1. Nguyên tắc chung

Mapping không được sinh tự do. Phải đi qua local candidate index.

```text
mention text
  -> normalize
  -> candidate generation
  -> rerank
  -> output top candidates
```

Vì candidate score dùng Jaccard, không nên trả quá nhiều mã nếu không chắc.

Policy đề xuất:

```text
confidence cao       -> top 1
ambiguous vừa        -> top 2-3
không chắc           -> [] hoặc top candidate nếu recall quan trọng hơn precision
```

Cần test bằng proxy metric nội bộ để chọn policy.

## 9.2. ICD-10 mapping cho `CHẨN_ĐOÁN`

Candidate generation:

```text
1. exact match với ICD name/synonym
2. normalized Vietnamese synonym
3. abbreviation map
4. fuzzy char n-gram
5. BM25 over ICD terms
6. optional dense retrieval
7. optional LLM constrained rerank trong candidate list
```

Ranking rule MVP:

```text
exact preferred name
> exact synonym
> abbreviation expansion exact
> high fuzzy score
> BM25 score
> section/context bonus
```

Cần chú ý:

- ICD-10 WHO vs ICD-10-CM có thể khác mã chi tiết.
- Một diagnosis có thể map nhiều mã hợp lý nếu thiếu thông tin subtype.
- Nên log top candidates để error analysis.

## 9.3. RxNorm mapping cho `THUỐC`

Candidate generation:

```text
1. full phrase exact
2. ingredient + strength
3. brand -> generic alias
4. ingredient only
5. fuzzy alias
6. optional constrained rerank
```

Drug normalization:

```text
cipro       -> ciprofloxacin
advil       -> ibuprofen
tylenol     -> acetaminophen/paracetamol
seroquel    -> quetiapine
coumadin    -> warfarin
bactrim     -> sulfamethoxazole/trimethoprim
eliquis     -> apixaban
```

Nếu có strength/form, ưu tiên RxCUI khớp strength. Nếu không có, dùng ingredient hoặc clinical drug gần nhất tùy RxNorm index.

---

## 10. Overlap resolution và post-processing

### 10.1. Merge overlap priority

Priority gợi ý:

```text
1. KẾT_QUẢ_XÉT_NGHIỆM nếu là value ngay sau lab name
2. TÊN_XÉT_NGHIỆM nếu pattern lab rõ
3. THUỐC nếu có drug name/strength rõ
4. CHẨN_ĐOÁN nếu nằm trong diagnosis/finding context
5. TRIỆU_CHỨNG
6. Auxiliary/non-target -> không output
```

Nếu cùng type overlap:

```text
- giữ span dài hơn nếu span dài có nghĩa y khoa đầy đủ
- giữ span ngắn hơn nếu span dài chứa trigger/context thừa
```

Ví dụ:

```text
"được chẩn đoán mắc bệnh trào ngược dạ dày"
  -> không lấy cả cụm
  -> lấy "bệnh trào ngược dạ dày"
```

### 10.2. Duplicate handling

Cùng text xuất hiện nhiều lần ở vị trí khác nhau:

- giữ nếu là occurrence khác nhau và có position khác nhau;
- không merge toàn cục theo text;
- chỉ loại duplicate nếu cùng `start/end/type`.

### 10.3. Final JSON validator

Validator bắt buộc:

```text
- JSON parse được
- output có đúng file 1.json ... 100.json
- mỗi item có type hợp lệ
- position là [int, int], start < end
- raw_text[start:end] == text
- assertions chỉ thuộc allowed set
- candidates là list string nếu có
- candidates chỉ meaningful cho CHẨN_ĐOÁN/THUỐC
- không có duplicate exact span/type
- không output auxiliary term rõ ràng
```

---

## 11. Kế hoạch dữ liệu

### 11.1. Tài nguyên cần chuẩn bị

```text
- ICD-10 local dictionary/index
- RxNorm local dictionary/index
- Vietnamese diagnosis/symptom dictionary
- Drug brand/generic alias map
- Lab name/abbreviation dictionary
- Section aliases
- Assertion triggers
- Noise normalization
- Non-target medical terms
```

### 11.2. Không dùng 10 mẫu làm nguồn chính

10 sample ban đầu chỉ dùng để khởi tạo ý tưởng. Với implementation thật:

```text
100 file -> span_candidates -> review -> derive dictionaries
```

Seed list phải được mở rộng từ toàn bộ 100 file và có version.

### 11.3. Weak labeling

Có thể tạo weak labels bằng:

```text
- dictionary exact/fuzzy match
- regex lab/drug
- section-aware rules
- abbreviation expansion
- assertion triggers
```

Weak labels dùng cho:

```text
- review nhanh
- synthetic generation
- optional NER fine-tuning
- error analysis
```

### 11.4. Manual review tối thiểu

Nếu có thời gian, review thủ công theo ưu tiên:

```text
1. 200-300 span thuốc + RxNorm mapping
2. 200-300 span chẩn đoán + ICD mapping
3. 200 span triệu chứng có negation/historical/family
4. 100 dòng lab/result khó
5. false positives từ non-target/procedure/imaging
```

Mục tiêu không phải annotate full 100 file, mà là sửa rule/dictionary tốt hơn.

### 11.5. Synthetic data

Sinh thêm data nếu cần train NER hoặc test rule:

```text
- câu triệu chứng hiện tại
- câu phủ định list triệu chứng
- câu tiền sử bệnh/thuốc
- câu family history
- câu thuốc có strength/route/frequency
- câu lab name + value + unit
- câu imaging method + finding
```

Synthetic phải lưu được offset tự động.

---

## 12. Evaluation và error analysis

### 12.1. Local metric proxy

Không dùng IoU làm metric chính. Metric proxy nên bám theo đề:

```text
Text:
- exact text match
- normalized WER
- boundary error rate

Assertion:
- Jaccard per entity
- false positive/false negative theo từng assertion

Candidate:
- candidate Jaccard
- Recall@1 / Recall@3 / Recall@5
- extra-candidate penalty analysis
```

NER F1 vẫn hữu ích để debug model, nhưng không đại diện hoàn toàn cho final score.

### 12.2. Error taxonomy

Mỗi lỗi nên gắn một nhóm:

```text
BAD_OFFSET
SPAN_TOO_LONG
SPAN_TOO_SHORT
WRONG_TYPE
MISSING_ENTITY
FALSE_POSITIVE_ENTITY
NEGATION_SCOPE_ERROR
HISTORICAL_SCOPE_ERROR
FAMILY_FALSE_POSITIVE
DRUG_ALIAS_MAPPING_ERROR
DRUG_STRENGTH_MAPPING_ERROR
ICD_AMBIGUOUS_MAPPING
LAB_VALUE_SPLIT_ERROR
PROCEDURE_AS_DIAGNOSIS
DIAGNOSIS_IN_LAB_SECTION_MISSED
DUPLICATE_ENTITY
```

### 12.3. Ablation plan

Ablation thực dụng:

```text
V0: section + regex lab + drug dictionary + diagnosis/symptom dictionary
V1: V0 + assertion rules
V2: V1 + ICD/RxNorm exact/fuzzy
V3: V2 + BM25
V4: V3 + improved overlap/validator
V5: V4 + optional NER
V6: V5 + optional LLM constrained fallback
```

Không nên thêm V5/V6 trước khi V0-V4 ổn.

---

## 13. Kế hoạch triển khai hackathon

### Ngày 1 - End-to-end baseline chắc

Mục tiêu: có submission chạy được.

```text
- Implement input reader cho test/input/*.txt
- Parse record/section/line
- Build section_aliases.json v2
- Implement offset-safe regex extraction
- Extract lab/result bằng regex + dictionary
- Extract drug bằng dictionary + dose parser cơ bản
- Extract diagnosis/symptom bằng dictionary
- Assertion rules cơ bản: negated/historical
- Output JSON đúng schema
- Offset validator
- make output.zip
```

Deliverable cuối ngày:

```text
output.zip hợp lệ
logs/errors/validation_report.json
span_candidates.jsonl bản đầu
```

### Ngày 2 - Tăng recall và mapping

Mục tiêu: bắt được nhiều entity hơn, mapping tốt hơn.

```text
- Review 20-30 file đại diện
- Mở rộng dictionaries từ span_candidates
- Add abbreviation_map
- Add noise_normalization
- Add non_target_medical_terms
- RxNorm alias + strength parser
- ICD exact/fuzzy/BM25
- Improve negation scope
- Add historical time_context
- Fix overlap resolver
```

Deliverable cuối ngày:

```text
V2 submission
error_analysis_top_cases.md
updated dictionaries/configs
```

### Ngày 3 - Error analysis và optional model/fallback

Mục tiêu: ổn định final.

```text
- Chạy full validation
- Review false positives/false negatives
- Sửa family strict rules
- Sửa lab section mixed finding
- Tối ưu candidate top-k policy
- Nếu còn thời gian: thêm NER weak-label hoặc LLM constrained fallback
- Freeze pipeline
```

Deliverable cuối ngày:

```text
final output.zip
source package
README reproduce
validation_report_final.json
```

---

## 14. Roadmap 4 tuần nếu có thời gian dài hơn

### Tuần 1 - Baseline và data layer

```text
- Hoàn thiện parser/section/line/span_candidates
- Build local ICD/RxNorm index
- Implement baseline extractor
- Implement validator
- Chạy V0-V2
```

### Tuần 2 - Weak data và NER

```text
- Review span_candidates
- Tạo weak/manual labels
- Sinh synthetic data
- Fine-tune thử XLM-R/PhoBERT/ViHealthBERT nếu đủ dữ liệu
- So sánh với rule baseline
```

### Tuần 3 - Mapping và rerank

```text
- BM25 ICD/RxNorm
- Fuzzy tuning
- Candidate top-k policy
- Optional dense retrieval
- Optional constrained LLM rerank
```

### Tuần 4 - Error analysis và freeze

```text
- Ablation V0-V6
- Assertion error analysis
- Offset/boundary tuning
- Reproducibility package
- Freeze final solution
```

---

## 15. Repository và triển khai kỹ thuật

### 15.1. Cấu trúc repo đề xuất

```text
project/
  README.md
  requirements.txt
  configs/
    section_aliases.json
    assertion_triggers.json
    noise_normalization.json
    extraction_rules.yaml
    mapping_config.yaml
  data_resources/
    icd10/
    rxnorm/
    dictionaries/
      diagnosis_seed_terms.csv
      symptom_seed_terms.csv
      drug_seed_terms.csv
      drug_context_terms.csv
      lab_seed_terms.csv
      abbreviation_map.csv
      non_target_medical_terms.csv
  src/
    predict.py
    io_utils.py
    preprocessing.py
    section_parser.py
    line_parser.py
    extractors/
      lab_extractor.py
      drug_extractor.py
      diagnosis_extractor.py
      symptom_extractor.py
    assertion.py
    mapping/
      icd_mapper.py
      rxnorm_mapper.py
      bm25.py
    postprocess.py
    validator.py
    zip_output.py
  scripts/
    build_data_assessment.py
    build_indices.py
    run_validation.py
    make_output_zip.py
  outputs/
  logs/
```

### 15.2. CLI chuẩn

```bash
python src/predict.py \
  --input_dir test/input \
  --output_dir output \
  --config configs/extraction_rules.yaml

python scripts/make_output_zip.py \
  --output_dir output \
  --zip_path output.zip
```

### 15.3. Log bắt buộc

```text
- number of files processed
- number of entities by type
- invalid offsets count
- empty outputs count
- candidates missing count for diagnosis/drug
- top reject reasons
- runtime per file
```

---

## 16. Submission và reproducibility

Do có khả năng BTC chạy lại trên private test, package phải reproduce được.

Checklist:

```text
- Không hard-code output theo 100 public files.
- Không phụ thuộc API ngoài runtime.
- Model weights nếu có phải đi kèm.
- ICD/RxNorm resources đi kèm hoặc có script build rõ ràng.
- README có hướng dẫn cài đặt và chạy inference.
- requirements.txt/environment.yml đầy đủ.
- predict.py nhận input_dir/output_dir bất kỳ.
- Fix random seed nếu có model.
- Có validation trước khi zip.
- Có log version dictionaries/rules.
```

README tối thiểu:

```text
1. Environment
2. Install dependencies
3. Prepare resources
4. Run prediction
5. Create output.zip
6. Expected output structure
7. Troubleshooting
```

---

## 17. Rủi ro và phương án giảm thiểu

| Rủi ro | Tác động | Giảm thiểu |
|---|---|---|
| Offset sai | mất text score, invalid output | raw_text validator bắt buộc |
| Candidate ICD/RxNorm sai | mất 40% score | local index + exact/fuzzy/BM25 + alias |
| Rule quá rộng gây false positive | giảm Jaccard/text | confidence threshold + non-target list |
| Assertion family sai | false positive assertion | strict family pattern |
| Historical quá rộng | gán sai thuốc/triệu chứng hiện tại | time_context + section prior mềm |
| Không có label train NER | model yếu | chỉ dùng NER sau weak/manual labels |
| LLM chậm/không ổn định | không reproduce | LLM optional fallback, không core |
| Private test format biến thể | parser fail | alias/noise config mở rộng, không hard-code |
| Dữ liệu RxNorm/ICD không khớp | candidate thấp | log unmatched, fallback ingredient/parent codes |

---

## 18. Definition of Done

Một bản solution được xem là đạt mức sẵn sàng khi:

```text
- Chạy end-to-end trên toàn bộ 100 file.
- Sinh đủ 100 file JSON.
- Tất cả JSON parse được.
- 100% predicted spans có raw_text[start:end] == text.
- Không có type/assertion ngoài allowed set.
- Có candidates cho diagnosis/drug khi mapping được.
- Có validation_report.json.
- Có output.zip đúng cấu trúc.
- Có README reproduce.
- Không phụ thuộc API ngoài.
- Có logs/error analysis đủ để debug.
```

---

## 19. Kết luận

Bản kế hoạch v2 nên được hiểu là blueprint triển khai thực tế:

```text
Data assessment layer
+ deterministic rule/dictionary MVP
+ local ICD/RxNorm mapping
+ strict assertion rules
+ overlap/offset validator
+ reproducible submission package
```

Những nâng cấp như NER, dense retrieval, cross-encoder hoặc LLM fallback chỉ nên thêm khi baseline đã ổn định. Với 100 file hiện tại, phần lợi thế lớn nhất nằm ở việc tận dụng cấu trúc section/subsection/line, xử lý tốt noise/abbreviation, và kiểm soát chặt offset + candidate mapping.
