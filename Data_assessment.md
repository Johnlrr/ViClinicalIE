# Data Assessment Requirements v2

## Bối cảnh và phạm vi

Tài liệu này mô tả yêu cầu đánh giá dữ liệu trước khi xây dựng solution chính cho bài toán trích xuất và chuẩn hóa khái niệm y khoa từ văn bản tự do. Bản này thay thế bản `data_assessment_requirements.md` cũ vốn được xây dựng từ 10 file mẫu ngẫu nhiên. Phiên bản mới được điều chỉnh theo quan sát trên file gộp `all.txt`, gồm 100 bản ghi từ `1.txt` đến `100.txt`.

Mục tiêu của bước data assessment không phải là annotate đầy đủ 100 file, mà là tạo một lớp phân tích có cấu trúc để phục vụ:

- rule baseline;
- dictionary/gazetteer expansion;
- candidate span review;
- assertion/context rule;
- ICD-10/RxNorm candidate linking;
- synthetic data generation;
- error analysis cho solution chính.

## Tóm tắt đặc điểm dữ liệu thực tế

Dữ liệu gồm 100 bản ghi clinical note bán cấu trúc. Mỗi bản ghi thường có 2-3 section lớn, nhưng không phải record nào cũng đủ section hoặc dùng đúng tên section. Độ dài giữa các record chênh lệch lớn: có record rất ngắn, có record dài nhiều nghìn ký tự.

Các đặc điểm nổi bật:

- Văn bản chủ yếu là tiếng Việt nhưng có nhiều thuật ngữ tiếng Anh, viết tắt và tên thuốc tiếng Anh.
- Cấu trúc lặp nhiều nhưng không chuẩn tuyệt đối.
- Có nhiều lỗi spacing, lỗi dính chữ, lỗi chính tả, lỗi dịch máy và header bị lặp.
- Có nhiều bullet, key-value line, đoạn văn tự do và câu ghép trong cùng một record.
- Một section có thể chứa nhiều loại thông tin khác nhau; ví dụ `Kết quả xét nghiệm` có thể chứa cả tên xét nghiệm, kết quả xét nghiệm và chẩn đoán/finding.
- Imaging/procedure xuất hiện nhiều nhưng không phải output target; tuy nhiên finding phía sau imaging/procedure có thể là `CHẨN_ĐOÁN`.



## Thống kê nhanh trên `all.txt`

| Chỉ số | Giá trị |
|---|---:|
| Số record parse theo marker `# N.txt` | 100 |
| Độ dài ký tự nhỏ nhất / trung vị / lớn nhất | 139 / 1,232 / 4,431 |
| Số token nhỏ nhất / trung vị / lớn nhất | 32 / 256 / 1,019 |
| Header phổ biến nhất | `Đánh giá tại bệnh viện`, `Tiền sử bệnh hiện tại`, `Tiền sử bệnh`, `Tiền sử bệnh nội khoa`, `Triệu chứng hiện tại` |
| Header/alias cần xử lý thêm | `Bệnh sử`, `Khám tại bệnh viện`, `Kết quả laboratory`, `Kết quả phòng thí nghiệm`, `Tiền sử bệnh bệnh hiện tại`, `Bệnh sử hin tại` |

Các con số này chỉ dùng để định hướng data profiling, không thay thế review thủ công span.

## Nhãn output cần phục vụ

Bước assessment phải hỗ trợ đúng các nhãn target của bài toán:

| Nhãn | Có cần assertion? | Có cần candidate mapping? | Mapping chuẩn |
|---|---:|---:|---|
| `TRIỆU_CHỨNG` | Có | Không | Không áp dụng |
| `CHẨN_ĐOÁN` | Có | Có | ICD-10 |
| `THUỐC` | Có | Có | RxNorm |
| `TÊN_XÉT_NGHIỆM` | Không | Không | Không áp dụng |
| `KẾT_QUẢ_XÉT_NGHIỆM` | Không | Không | Không áp dụng |

Assertion chỉ xét tối đa 3 nhãn:

```text
isNegated
isHistorical
isFamily
```

Không tạo thêm nhãn output như `THỦ_THUẬT`, `CHẨN_ĐOÁN_HÌNH_ẢNH`, `VITAL_SIGN`, `RISK_FACTOR`. Các nhóm này chỉ được lưu trong auxiliary/blacklist/graylist để hỗ trợ context và tránh false positive.

## Nguyên tắc thiết kế data assessment

### 1. Không dùng một dictionary làm nguồn sự thật duy nhất

Không nên viết thủ công nhiều file dictionary độc lập ngay từ đầu. Nên tạo `span_candidates` làm bảng trung gian chính, sau đó review và derive các dictionary từ bảng này.

Luồng đúng:

```text
raw text
→ record inventory
→ section/subsection inventory
→ line table
→ span_candidates
→ manual review một phần
→ seed dictionaries / rule lists
→ baseline extraction
```

### 2. Không gán assertion chỉ bằng section

Section chỉ là prior, không phải rule tuyệt đối.

Ví dụ:

- `Tiền sử bệnh` có prior mạnh cho `isHistorical`.
- `Thuốc trước khi nhập viện` có prior mạnh cho `isHistorical` đối với thuốc.
- `Các sự kiện trước khi nhập viện` chỉ là prior yếu, vì có thể chứa cả triệu chứng đang hoạt động, thuốc dùng tại cấp cứu, kết quả mới và chẩn đoán hiện tại.
- `người nhà`, `gia đình`, `cháu gái` không đủ để gán `isFamily`; cần pattern cho thấy bệnh/triệu chứng thuộc về người thân.

### 3. Không ép type theo section một cách cứng nhắc

Một section có thể chứa nhiều loại span.

Ví dụ:

- Trong `Kết quả xét nghiệm`, có thể có `glucose 537`, nhưng cũng có thể có `suy thận cấp`, `bất thường điện giải` (mà mấy cái này thì giống `CHẨN_ĐOÁN` hơn).
- Trong `Kết quả chẩn đoán hình ảnh`, `chụp CT` không phải output, nhưng `viêm túi mật thủng cấp tính` phía sau có thể là `CHẨN_ĐOÁN`.
- Trong `Thuốc trước khi nhập viện`, có thể có tên thuốc thật, nhưng cũng có cụm chung như `thuốc giảm đau`, `liệu pháp lợi tiểu`, không nên map RxNorm nếu không có tên cụ thể.

### 4. Ưu tiên offset chính xác ngay từ đầu

Mọi bảng trung gian phải lưu `start`, `end` theo offset ký tự của raw text. Không chỉ lưu normalized text. Vì output cuối cần `position`, và metric text bị ảnh hưởng trực tiếp bởi boundary.

### 5. Giữ raw text và normalized text song song

Không được thay raw text khi tính offset. Mọi normalization chỉ lưu ở field riêng.

Ví dụ:

```json
{
  "text": "atenololtrong ngày",
  "normalized_text": "atenolol trong ngày",
  "start": 123,
  "end": 139
}
```

## Đầu ra bắt buộc của bước data assessment

Bước assessment cần tạo ít nhất 8 đầu ra sau:

```text
1. records_inventory.csv
2. section_inventory.jsonl
3. line_table.jsonl
4. span_candidates.jsonl
5. assertion_trigger_inventory.json
6. normalization_inventory.json
7. auxiliary_non_target_terms.csv
8. assessment_report.md
```

Các dictionary seed như `diagnosis_seed_terms.csv`, `symptom_seed_terms.csv`, `drug_seed_terms.csv`, `lab_seed_terms.csv` chỉ nên được sinh sau khi đã review `span_candidates`.

---

# 1. Record inventory

## Mục tiêu

Xác nhận toàn bộ 100 record được parse đúng từ file gộp và có metadata cơ bản để phân tích.

## File đầu ra

`records_inventory.csv`

## Schema bắt buộc

| Cột | Mô tả |
|---|---|
| `file_id` | Ví dụ `1.txt`, `57.txt` |
| `record_index` | Số thứ tự record |
| `char_len` | Độ dài ký tự raw body |
| `word_count` | Số token theo whitespace |
| `line_count` | Số dòng |
| `has_past_history` | Có section tiền sử hay không |
| `has_current_history` | Có section bệnh sử hiện tại hay không |
| `has_hospital_assessment` | Có section đánh giá tại viện hay không |
| `has_lab_section` | Có section xét nghiệm/cận lâm sàng hay không |
| `has_imaging_section` | Có section hình ảnh hay không |
| `has_medication_section` | Có section thuốc hay không |
| `notes` | Ghi chú bất thường |

## Requirement

- Parse đúng đủ 100 record.
- Không mất record ngắn hoặc record không có header đánh số.
- Phát hiện được record có cấu trúc lạ như chỉ có `Bệnh sử`, chỉ có `Lý do nhập viện`, hoặc thiếu `Đánh giá tại bệnh viện`.

---

# 2. Section và subsection inventory

## Mục tiêu

Tách văn bản thành các section/subsection có hierarchy để hỗ trợ rule, assertion và chunking.

## File đầu ra

`section_inventory.jsonl`

## Schema bắt buộc

```json
{
  "file_id": "1.txt",
  "section_id": "1.txt::sec_0003",
  "parent_section_id": "1.txt::sec_0001",
  "raw_header": "Các triệu chứng hiện tại",
  "normalized_header": "cac trieu chung hien tai",
  "section_type": "CURRENT_SYMPTOMS",
  "section_role": "SUBSECTION",
  "level": 2,
  "start": 401,
  "end": 428,
  "content_start": 429,
  "content_end": 712,
  "confidence": 0.95,
  "source": ["regex_header", "alias_match"]
}
```

## Section ontology đề xuất

### Main section

| section_type | Mục đích |
|---|---|
| `PAST_HISTORY` | Tiền sử bệnh, bệnh mạn tính, phẫu thuật cũ, thuốc trước nhập viện |
| `CURRENT_HISTORY` | Bệnh sử hiện tại, lý do nhập viện, diễn biến hiện tại |
| `HOSPITAL_ASSESSMENT` | Đánh giá tại bệnh viện, khám tại viện, kết quả cận lâm sàng |
| `UNKNOWN_MAIN` | Main section không map chắc chắn |

### Subsection

| section_type | Mục đích |
|---|---|
| `CHRONIC_DISEASES` | Các bệnh lý mạn tính/mãn tính |
| `PAST_PROCEDURE_HISTORY` | Tiền sử phẫu thuật/thủ thuật |
| `MEDICATION_HISTORY` | Thuốc trước nhập viện / đang dùng trước nhập viện |
| `MEDICATION_ADMINISTERED` | Thuốc đã dùng tại viện/cấp cứu hoặc được chỉ định trong diễn biến hiện tại |
| `RISK_FACTOR` | Yếu tố nguy cơ, rượu, thuốc lá, caffeine, nghề nghiệp |
| `ADMISSION_REASON` | Lý do nhập viện / lý do vào viện |
| `ONSET_TIME` | Thời điểm khởi phát |
| `DISEASE_COURSE` | Diễn biến bệnh |
| `CURRENT_SYMPTOMS` | Triệu chứng hiện tại / triệu chứng khi nhập viện |
| `SYMPTOM_DETAIL` | Đặc điểm triệu chứng, vị trí, mức độ, thời gian, yếu tố liên quan |
| `PRE_ADMISSION_EVENTS` | Sự kiện/diễn biến trước nhập viện |
| `IMMEDIATE_PRE_ADMISSION_STATUS` | Tình trạng ngay trước nhập viện / lúc vào viện |
| `PHYSICAL_EXAM` | Khám thực thể, khám lâm sàng, dấu hiệu lâm sàng |
| `LAB_RESULT_SECTION` | Kết quả xét nghiệm, phòng thí nghiệm, laboratory, cận lâm sàng |
| `IMAGING_RESULT_SECTION` | Kết quả chẩn đoán hình ảnh, hình ảnh, chụp ảnh |
| `PROCEDURE_SECTION` | Thủ thuật đã thực hiện |
| `DIAGNOSTIC_FINDINGS` | Các phát hiện chẩn đoán khác, chẩn đoán sơ bộ, chẩn đoán |
| `UNKNOWN_SUBSECTION` | Subsection chưa map chắc chắn |

## Alias bắt buộc cần bao phủ

### `PAST_HISTORY`

```text
Tiền sử bệnh
Tiền sử bệnh nội khoa
Tiền sử bệnh lý
Bệnh lý mãn tính
Bệnh lý mạn tính
Bệnh mạn tính
Các bệnh lý mãn tính
Các bệnh lý mạn tính
Các bệnh lý nội khoa mạn tính
Các bệnh mãn tính
```

### `CURRENT_HISTORY`

```text
Tiền sử bệnh hiện tại
Bệnh sử hiện tại
Bệnh sử  hiện tại
Lịch sử bệnh hiện tại
Bệnh sử
Tiền sử bệnh bệnh hiện tại
Bệnh sử hin tại
```

### `HOSPITAL_ASSESSMENT`

```text
Đánh giá tại bệnh viện
Khám tại bệnh viện
khám  tại bệnh viện
Kết quả khám tại bệnh viện
Khám thấy
```

### `LAB_RESULT_SECTION`

```text
Kết quả xét nghiệm
Kết quả xét nghiệm máu
Kết quả phòng thí nghiệm
Kết quả laboratory
Xét nghiệm
Cận lâm sàng
```

### `IMAGING_RESULT_SECTION`

```text
Kết quả chẩn đoán hình ảnh
Kết quả hình ảnh
Kết quả chụp ảnh
Kết quả chụp ảnh/kỹ thuật chẩn đoán hình ảnh
Chẩn đoán hình ảnh
Chẩn đoán hình ảnh và thăm dò
```

### `MEDICATION_HISTORY`

```text
Thuốc trước khi nhập viện
Thuốc trước khi nhập viện lần này
Thuốc đang dùng trước khi nhập viện
Thuốc đang điều trị theo đơn
Thuốc đã dùng trước đây
Bệnh nhân có tiền sử dụng thuốc
```

### `MEDICATION_ADMINISTERED`

```text
Các thuốc đã thực hiện
Được cho
Được chỉ định điều trị
Được điều trị bằng
Dùng kháng sinh tĩnh mạch
```

## Cảnh báo

Không nên coi tất cả alias là cùng level. Ví dụ `Các bệnh lý mạn tính` thường là subsection của `PAST_HISTORY`, không phải main section độc lập. Cần lưu `parent_section_id` và `section_role`.

---

# 3. Line table

## Mục tiêu

Chuyển mỗi record thành các dòng có metadata để hỗ trợ rule extraction, đặc biệt với bullet và key-value line.

## File đầu ra

`line_table.jsonl`

## Schema bắt buộc

```json
{
  "file_id": "1.txt",
  "line_id": "1.txt::line_0017",
  "section_id": "1.txt::sec_0003",
  "section_type": "CURRENT_SYMPTOMS",
  "raw_line": "- khó thở (khởi phát lúc 17 giờ)",
  "clean_line": "khó thở (khởi phát lúc 17 giờ)",
  "line_type": "BULLET",
  "key": null,
  "value": "khó thở (khởi phát lúc 17 giờ)",
  "start": 512,
  "end": 545,
  "indent_level": 1
}
```

## `line_type` đề xuất

```text
HEADER
BULLET
KEY_VALUE
FREE_TEXT
EMPTY
TABLE_LIKE
MALFORMED
```

## Requirement

- Giữ offset dòng theo raw text.
- Không xóa bullet trước khi tính offset.
- Với dòng dạng `Kết quả xét nghiệm: glucose 537`, phải tách được `key = Kết quả xét nghiệm`, `value = glucose 537`.
- Với dòng dạng `- ast ... là 319`, vẫn giữ line là bullet và để span extractor xử lý entity bên trong.

---

# 4. Span candidates

## Mục tiêu

Tạo bảng candidate span duy nhất cho mọi loại entity có thể output hoặc có thể hỗ trợ output.

## File đầu ra

`span_candidates.jsonl`

## Schema bắt buộc

```json
{
  "file_id": "5.txt",
  "span_id": "5.txt::span_0012",
  "text": "bệnh trào ngược dạ dày- thực quản không có viêm thực quản",
  "normalized_text": "benh trao nguoc da day thuc quan khong co viem thuc quan",
  "start": 125,
  "end": 187,
  "type_candidate": "CHẨN_ĐOÁN",
  "type_confidence": 0.87,
  "section_id": "5.txt::sec_0002",
  "section_type": "CHRONIC_DISEASES",
  "parent_section_type": "PAST_HISTORY",
  "line_id": "5.txt::line_0007",
  "line_text": "- bệnh trào ngược dạ dày- thực quản không có viêm thực quản",
  "left_context": "- tăng lipid máu, không đặc hiệu\n- ",
  "right_context": "\n\n2. Tiền sử bệnh hiện tại",
  "source": ["section_rule", "dictionary", "ner"],
  "time_context": "past",
  "assertion_candidates": ["isHistorical"],
  "mapping_candidates": [],
  "should_output": true,
  "span_status": "candidate",
  "reject_reason": null,
  "notes": "Needs ICD linking"
}
```

## Cột bắt buộc

| Cột | Mục đích |
|---|---|
| `file_id` | Gắn với record |
| `span_id` | ID duy nhất |
| `text` | Raw span đúng với input |
| `normalized_text` | Bản chuẩn hóa phục vụ retrieval |
| `start`, `end` | Offset raw text |
| `type_candidate` | Một trong 5 target hoặc auxiliary type |
| `type_confidence` | Điểm tin cậy |
| `section_type` | Section/subsection chứa span |
| `parent_section_type` | Main section chứa span |
| `line_text` | Dòng gốc để debug |
| `left_context`, `right_context` | Cửa sổ context |
| `source` | Regex/dictionary/NER/LLM/rule |
| `time_context` | past/current/pre_admission/in_hospital/unknown |
| `assertion_candidates` | Candidate assertion |
| `mapping_candidates` | ICD/RxNorm candidates nếu có |
| `should_output` | Có nên output hay không |
| `span_status` | candidate/accepted/rejected/needs_review |
| `reject_reason` | Lý do reject nếu có |

## `type_candidate` cho target

```text
TRIỆU_CHỨNG
CHẨN_ĐOÁN
THUỐC
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
```

## `type_candidate` cho auxiliary

```text
PROCEDURE_OR_IMAGING
VITAL_SIGN
RISK_FACTOR
BODY_PART
DOSAGE_ROUTE_FREQUENCY
GENERAL_TREATMENT_TERM
ADMINISTRATIVE_EVENT
UNKNOWN_MEDICAL_TERM
```

Auxiliary span mặc định `should_output = false`, nhưng được dùng để:

- tránh output nhầm;
- tìm finding phía sau imaging/procedure;
- hỗ trợ cắt span thuốc;
- hỗ trợ assertion/context.

---

# 5. Requirement theo từng loại span target

## 5.1 `CHẨN_ĐOÁN`

### Nguồn trích xuất ưu tiên

```text
- CHRONIC_DISEASES
- ADMISSION_REASON
- DIAGNOSTIC_FINDINGS
- IMAGING_RESULT_SECTION, nhưng chỉ lấy finding
- LAB_RESULT_SECTION, nếu dòng là disease/finding phrase
- PRE_ADMISSION_EVENTS, nếu có pattern chẩn đoán/phát hiện
```

### Ví dụ dạng cần bắt

```text
tăng huyết áp
đái tháo đường
xơ gan do rượu
hội chứng não gan
rung nhĩ
nhồi máu cơ tim vùng dưới cũ
viêm túi mật cấp
viêm túi mật thủng cấp tính
sỏi ống mật chủ
bệnh trào ngược dạ dày-thực quản không có viêm thực quản
ung thư đại tràng
ung thư phổi không tế bào nhỏ
bóc tách động mạch chủ Stanford loại B
```

### Cảnh báo

- Không output phương tiện chẩn đoán như `chụp CT`, `siêu âm`, `MRI`, `nội soi`, `điện tâm đồ`.
- Không reject finding chỉ vì nó nằm trong imaging/lab section.
- Cần phân biệt bệnh/chẩn đoán với triệu chứng: `đau bụng` thường là triệu chứng, `viêm túi mật cấp` là chẩn đoán.
- Các cụm như `không đặc hiệu`, `nghi ngờ`, `theo dõi`, `lo ngại` không nhất thiết là một phần chính của span; cần review boundary theo metric.

## 5.2 `TRIỆU_CHỨNG`

### Nguồn trích xuất ưu tiên

```text
- ADMISSION_REASON
- CURRENT_SYMPTOMS
- SYMPTOM_DETAIL
- DISEASE_COURSE
- IMMEDIATE_PRE_ADMISSION_STATUS
- PHYSICAL_EXAM, nếu là dấu hiệu/triệu chứng quan sát được
```

### Ví dụ dạng cần bắt

```text
khó thở
đánh trống ngực
đau ngực
cảm giác thắt chặt ngực
sốt
buồn nôn
nôn
ớn lạnh
mệt mỏi
ho
ho ra máu
đờm hồng
đau bụng vùng hạ sườn phải
đau bụng vùng thượng vị
chóng mặt
ảo giác thị giác
ảo thanh
phù chân
```

### Cảnh báo

- Có nhiều span nested: `đau bụng`, `đau bụng vùng hạ sườn phải`, `đau bụng vùng thượng vị`. Cần thống nhất chiến lược span dài/ngắn trước khi train, nhưng nên ưu tiên chi tiết để bắt ICD-10 tốt hơn.
- Dòng `Đặc điểm triệu chứng` có nhiều field như `Vị trí`, `Thời gian`, `Mức độ`, không phải tất cả đều là entity.
- Dấu hiệu phủ định thường xuất hiện trong danh sách dài: `Không có sốt, ớn lạnh, nôn, táo bón, ho...`. Cần apply negation scope cho từng triệu chứng.

## 5.3 `THUỐC`

### Nguồn trích xuất ưu tiên

```text
- MEDICATION_HISTORY
- MEDICATION_ADMINISTERED
- DISEASE_COURSE, nếu có động từ dùng/cho/chỉ định/ngừng thuốc
- PRE_ADMISSION_EVENTS, nếu có tên thuốc cụ thể
```

### Ví dụ dạng cần bắt

```text
metoprolol 25mg po bid
doxycycline
atenolol
aspirin 325mg
omeprazole
vancomycin 1 gram
levofloxacin 750mg iv
bumetanide 2mg iv
gleevec
allopurinol
coumadin
eliquis
lasix
methadone
flagyl
```

### Tách `drug_seed_terms` và `drug_context_terms`

Không đưa các cụm chung vào `drug_seed_terms.csv`.

#### `drug_seed_terms.csv`

Chỉ chứa tên thuốc/biệt dược/hoạt chất có thể map RxNorm.

```text
metoprolol
aspirin
omeprazole
vancomycin
levofloxacin
bactrim
cipro
seroquel
gleevec
allopurinol
coumadin
eliquis
lasix
flagyl
methadone
```

#### `drug_context_terms.csv`

Chỉ dùng làm context trigger, không output trực tiếp nếu không có tên thuốc cụ thể.

```text
kháng sinh
kháng sinh tĩnh mạch
thuốc giảm đau
thuốc giảm đau opioid
liệu pháp lợi tiểu
chống đông
điều trị nội khoa
```

### Assertion cho thuốc

- `MEDICATION_HISTORY` → prior mạnh cho `isHistorical`.
- `MEDICATION_ADMINISTERED` → không mặc định `isHistorical`.
- `ngừng`, `đã dừng`, `đã ngừng` cần lưu nhưng không tự động tương đương `isHistorical` nếu ngữ cảnh là hiện tại gần.

## 5.4 `TÊN_XÉT_NGHIỆM`

### Nguồn trích xuất ưu tiên

```text
- LAB_RESULT_SECTION
- PHYSICAL_EXAM hoặc DIAGNOSTIC_FINDINGS nếu có test name rõ
- Inline patterns dạng test + value
```

### Ví dụ dạng cần bắt

```text
glucose
bun
cr
ag
ast
alt
bilirubin toàn phần
bạch cầu
wbc
troponin
huyết cầu tố
cea
lipase
công thức máu
chức năng gan
phân tích nước tiểu
```

### Cảnh báo

- `công thức máu là 32` có thể là test name + result, nhưng cần review vì value có thể không chuẩn.
- Một dòng lab có thể chứa diagnosis/finding; không ép toàn bộ dòng thành lab.
- Các kết quả định tính như `âm tính`, `dương tính`, `bình thường`, `đang chờ`, `tăng nhẹ` cần xử lý như result nếu gắn với test.

## 5.5 `KẾT_QUẢ_XÉT_NGHIỆM`

### Pattern cần hỗ trợ

```text
test value
test là value
test: value
test tăng nhẹ lên value
test cải thiện thành value
test âm tính / dương tính / bình thường / đang chờ
```

### Ví dụ dạng cần bắt

```text
537
367
3
1.2
17
319
690
2.4
11.6
26.1
âm tính
dương tính
bình thường
đang chờ
tăng nhẹ
```

### Cảnh báo

- Không lấy vital signs lẫn vào lab result nếu không có test context.
- Không lấy toàn bộ câu mô tả như `không có gì đáng chú ý` nếu schema annotation thực tế chỉ lấy giá trị ngắn; cần review mẫu output nếu có.

---

# 6. Assertion trigger inventory

## File đầu ra

`assertion_trigger_inventory.json`

## Schema đề xuất

```json
{
  "isNegated": {
    "triggers": ["không", "không có", "không ghi nhận", "không phát hiện", "âm tính", "phủ nhận"],
    "scope_terminators": ["nhưng", "tuy nhiên", ";", ".", "ngoài ra"],
    "notes": "Apply per entity, not per full sentence blindly"
  },
  "isHistorical": {
    "triggers": ["tiền sử", "trước đây", "đã từng", "mạn tính", "mãn tính", "trước nhập viện", "lần nhập viện trước"],
    "section_priors": ["PAST_HISTORY", "MEDICATION_HISTORY"],
    "notes": "PRE_ADMISSION_EVENTS is weak prior only"
  },
  "isFamily": {
    "triggers": ["bố", "mẹ", "cha", "anh", "chị", "em", "con", "gia đình", "họ hàng"],
    "required_patterns": ["family_member + có/bị/mắc/tiền sử/chẩn đoán + entity"],
    "notes": "Do not mark family when family member is only narrator"
  }
}
```

## `isNegated` requirement

Cần nhận diện các pattern:

```text
không
không có
không ghi nhận
không phát hiện
không thấy
không cho thấy
không đáng chú ý
âm tính
phủ nhận
chưa phát hiện
```

Cần xử lý list phủ định:

```text
Không có sốt, ớn lạnh, nôn, táo bón, ho, tiểu khó
```

Mỗi entity trong list phải được xét assertion riêng.

## `isHistorical` requirement

Cần dùng kết hợp section prior và trigger:

```text
tiền sử
mạn tính / mãn tính
trước đây
đã từng
gần đây nhập viện vì
lần nhập viện trước
trước khi nhập viện
thuốc trước khi nhập viện
đã phẫu thuật
đã ngừng / đã dừng
```

Không nên gán `isHistorical` cho toàn bộ `PRE_ADMISSION_EVENTS` nếu không có trigger cụ thể.

## `isFamily` requirement

Cần rất strict. Không gán `isFamily` trong các trường hợp:

```text
người nhà nhận thấy bệnh nhân...
gia đình lo ngại tình trạng bệnh...
cháu gái hét lên...
```

Chỉ gán nếu bệnh/triệu chứng thuộc về người thân:

```text
bố bệnh nhân có tiền sử...
mẹ bệnh nhân mắc...
nhiều người trong gia đình có triệu chứng tương tự...
```

---

# 7. Normalization và noise inventory

## File đầu ra

`normalization_inventory.json`

## Nhóm lỗi cần lưu

### 7.1 Header typo / alias noise

```text
Bệnh sử hin tại → Bệnh sử hiện tại
Tiền sử bệnh bệnh hiện tại → Tiền sử bệnh hiện tại
Kêt quả → Kết quả
Các biến trước khi nhập viện → Các diễn biến trước khi nhập viện
```

### 7.2 Spacing / concatenation noise

```text
cảm giáckhó chịu → cảm giác khó chịu
atenololtrong ngày → atenolol trong ngày
doxycyclinebactrim → doxycycline bactrim
albuterolipratropium → albuterol ipratropium
Dùngmethadonekéo dài → Dùng methadone kéo dài
lasixđã dừng → lasix đã dừng
```

### 7.3 Repetition noise

```text
bình thườngbình thườngbình thường
mệt mỏi / mệt mỏi repeated bullets
khó thở nhẹ khó thở
```

### 7.4 Mixed-language terms

```text
lower abdominal pain
fever
course of ertapenem
oral suspension
po daily
iv
prn
qhs
qam
```

## Requirement

- Không sửa raw text dùng cho offset.
- Chỉ dùng normalization để hỗ trợ matching, section detection và candidate linking.
- Mỗi normalization rule cần có `error_type` và ví dụ file nếu có.

Schema:

```json
{
  "raw_pattern": "Bệnh sử  hin tại",
  "normalized": "Bệnh sử hiện tại",
  "error_type": "typo_section_header",
  "apply_to": ["section_detection"],
  "safe_for_offset_repair": false,
  "examples": ["95.txt"]
}
```

---

# 8. Auxiliary non-target terms

## File đầu ra

`auxiliary_non_target_terms.csv`

## Mục tiêu

Lưu các cụm y khoa không phải output target, nhưng cần dùng để tránh false positive hoặc làm context.

## Nhóm cần có

### 8.1 Procedure/imaging method

```text
chụp x-quang
chụp ct
chụp cắt lớp vi tính
mri
siêu âm
siêu âm Doppler
điện tâm đồ
ecq / ecg
monitor holter
nội soi
nội soi mật tụy ngược dòng
ERCP
chọc hút bằng kim nhỏ
chọc dò dịch não tủy
sinh thiết
dẫn lưu dịch
đặt stent
đặt nội khí quản
đặt catheter
```

### 8.2 Administrative/event terms

```text
nhập viện
xuất viện
chuyển viện
tái khám
đến khoa cấp cứu
gọi xe cứu thương
ký giấy đồng ý
```

### 8.3 Vital sign / measurement context

```text
huyết áp
mạch
nhịp thở
SpO2
nhiệt độ
RA
2LNC
VS
```

### 8.4 General treatment terms

```text
kháng sinh
kháng sinh tĩnh mạch
liệu pháp lợi tiểu
thuốc giảm đau
điều trị bảo tồn
điều trị nội khoa
điều trị ngoại khoa
```

## Cảnh báo quan trọng

Không được blacklist cả câu. Chỉ blacklist method hoặc term chung.

Ví dụ:

```text
chụp CT cho thấy viêm túi mật thủng cấp tính
```

- `chụp CT` → auxiliary, không output.
- `viêm túi mật thủng cấp tính` → có thể là `CHẨN_ĐOÁN`, cần output nếu đúng context.

---

# 9. Abbreviation và bilingual inventory

## File đầu ra

`abbreviation_map.csv`

## Schema đề xuất

| Cột | Mô tả |
|---|---|
| `abbr` | Viết tắt raw |
| `expanded_en` | Diễn giải tiếng Anh |
| `expanded_vi` | Diễn giải tiếng Việt |
| `preferred_type` | Target/auxiliary type |
| `notes` | Ghi chú ambiguity |

## Ví dụ cần có

```text
CBC → complete blood count → công thức máu → TÊN_XÉT_NGHIỆM
CT → computed tomography → chụp cắt lớp vi tính → PROCEDURE_OR_IMAGING
MRI → magnetic resonance imaging → chụp cộng hưởng từ → PROCEDURE_OR_IMAGING
UA → urinalysis → phân tích nước tiểu → TÊN_XÉT_NGHIỆM
DVT → deep vein thrombosis → huyết khối tĩnh mạch sâu → CHẨN_ĐOÁN
AH → auditory hallucination → ảo thanh → TRIỆU_CHỨNG
LLQ → left lower quadrant → hạ vị/góc phần tư dưới trái → BODY_PART
BUN → blood urea nitrogen → ure máu → TÊN_XÉT_NGHIỆM
Cr → creatinine → creatinine → TÊN_XÉT_NGHIỆM
AG → anion gap → khoảng trống anion → TÊN_XÉT_NGHIỆM
ALT → alanine aminotransferase → men gan ALT → TÊN_XÉT_NGHIỆM
AST → aspartate aminotransferase → men gan AST → TÊN_XÉT_NGHIỆM
```

## Cảnh báo

Một viết tắt có thể đổi nghĩa theo context. Ví dụ `CT` là imaging method, không phải diagnosis; `AH` có thể là abbreviation của ảo thanh trong tâm thần.

---

# 10. Review workflow

## Mục tiêu review

Không annotate full 100 file ngay. Chỉ cần review có chiến lược để tinh chỉnh rule và seed dictionary.

## Quy trình đề xuất

```text
Bước 1: Parse 100 record thành records_inventory, section_inventory, line_table.
Bước 2: Extract candidate span bằng regex + dictionary seed thô + section hints.
Bước 3: Sinh span_candidates.jsonl.
Bước 4: Review 300-500 span đầu tiên theo stratified sampling.
Bước 5: Gắn span_status: accepted/rejected/needs_review.
Bước 6: Derive seed dictionaries từ accepted spans.
Bước 7: Chạy baseline lại.
Bước 8: Review lỗi false positive/false negative theo từng type.
```

## Stratified sampling bắt buộc

Mỗi batch review phải có span từ các nhóm:

```text
- CHẨN_ĐOÁN trong PAST_HISTORY
- CHẨN_ĐOÁN trong IMAGING_RESULT_SECTION
- TRIỆU_CHỨNG bị phủ định
- TRIỆU_CHỨNG hiện tại
- THUỐC trước nhập viện
- THUỐC được cho tại viện
- LAB test + numeric result
- LAB test + qualitative result
- auxiliary procedure/imaging method
- family/narrator context
```

## Nhãn review

```text
accepted
rejected
needs_review
boundary_error
type_error
assertion_error
mapping_error
not_target_auxiliary
```

---

# 11. Quality checklist

## 11.1 Record parsing

- [ ] Parse đủ 100 record.
- [ ] Không mất record ngắn.
- [ ] Không merge nhầm hai record liên tiếp.
- [ ] `file_id` giữ đúng `1.txt` đến `100.txt`.

## 11.2 Section parsing

- [ ] Bao phủ main section phổ biến.
- [ ] Bao phủ header không đánh số như `Bệnh sử`.
- [ ] Bao phủ typo section như `Bệnh sử hin tại`.
- [ ] Có parent-child hierarchy.
- [ ] Không ép subsection thành main section nếu không cần.

## 11.3 Line parsing

- [ ] Bullet giữ được offset.
- [ ] Key-value line được tách key/value.
- [ ] Đoạn free-text dài không bị bỏ qua.
- [ ] Các dòng dính section như `.Đánh giá tại bệnh viện` vẫn được detect.

## 11.4 Span candidates

- [ ] Mỗi span có raw text, start, end.
- [ ] `text == raw_text[start:end]` với toàn bộ span output candidate.
- [ ] Có normalized_text nhưng không thay raw text.
- [ ] Có source và confidence.
- [ ] Có should_output/span_status/reject_reason.

## 11.5 Assertion

- [ ] Không gán `isHistorical` chỉ vì nằm trong `PRE_ADMISSION_EVENTS`.
- [ ] Không gán `isFamily` khi người nhà chỉ là narrator.
- [ ] Negation scope xử lý được list triệu chứng.
- [ ] `âm tính`, `không phát hiện`, `không ghi nhận` được xử lý khác nhau tùy test/finding/symptom.

## 11.6 Drug

- [ ] Tên thuốc cụ thể tách khỏi cụm điều trị chung.
- [ ] `kháng sinh`, `thuốc giảm đau`, `liệu pháp lợi tiểu` không output trực tiếp nếu không có tên thuốc.
- [ ] Có pattern strength/unit/route/frequency.
- [ ] Có brand-generic alias cho thuốc phổ biến.

## 11.7 Lab

- [ ] Nhận diện numeric result.
- [ ] Nhận diện qualitative result.
- [ ] Không ép diagnosis trong lab section thành lab.
- [ ] Không nhầm vital signs thành lab nếu không có test context.

## 11.8 Auxiliary

- [ ] Procedure/imaging method không output.
- [ ] Finding phía sau procedure/imaging vẫn được giữ làm candidate diagnosis.
- [ ] Vital sign và administrative event được graylist.

---

# 12. Các lỗi/nhiễu cần theo dõi trong report

`assessment_report.md` cần có ít nhất các mục:

```text
1. Số record parse được
2. Thống kê độ dài record
3. Top section/header alias
4. Các section chưa map được
5. Top typo/noise pattern
6. Số span candidate theo type
7. Số span auxiliary theo nhóm
8. Tỉ lệ span có offset hợp lệ
9. Top false positive sau review
10. Top false negative sau review
11. Các ambiguity cần quyết định trước khi train
```

## Ambiguity cần quyết định sớm

### Span dài hay span ngắn

Ví dụ:

```text
đau bụng
đau bụng vùng hạ sườn phải
đau bụng vùng thượng vị
```

Cần thống nhất annotation strategy cho model và post-processing.

### Diagnosis vs symptom

Ví dụ:

```text
hạ huyết áp
sốt
phù
thiếu oxy
```

Một số cụm có thể là symptom/sign hoặc diagnosis tùy annotation guideline. Cần review theo output mẫu nếu có.

### Lab result phrase length

Ví dụ:

```text
âm tính
không có gì đáng chú ý
bình thường
đang chờ
```

Cần quyết định span result nên lấy ngắn hay cả phrase.

### Medication span boundary

Ví dụ:

```text
metoprolol 25mg po bid
aspirin 325mg x 1
levofloxacin 750mg iv
```

Cần thống nhất có lấy route/frequency/dose count vào span hay không. Output mẫu của đề cho thấy thuốc thường lấy cả strength/route/frequency nếu xuất hiện.

---

# 13. Đề xuất thứ tự thực hiện

## Phase 1: Structural profiling

Deliverables:

```text
records_inventory.csv
section_inventory.jsonl
line_table.jsonl
assessment_report.md bản đầu
```

Mục tiêu: hiểu cấu trúc 100 file, thống kê alias và noise.

## Phase 2: Candidate span extraction

Deliverables:

```text
span_candidates.jsonl
auxiliary_non_target_terms.csv
normalization_inventory.json
abbreviation_map.csv
```

Mục tiêu: có candidate span đủ rộng để review.

## Phase 3: Manual review nhỏ nhưng có chiến lược

Deliverables:

```text
reviewed_span_candidates.jsonl
review_summary.md
```

Mục tiêu: lấy accepted/rejected span để tạo seed dictionaries.

## Phase 4: Derive seed dictionaries

Deliverables:

```text
diagnosis_seed_terms.csv
symptom_seed_terms.csv
drug_seed_terms.csv
drug_context_terms.csv
lab_seed_terms.csv
assertion_triggers.json
```

Mục tiêu: chuẩn bị cho baseline extraction và synthetic data.

## Phase 5: Baseline-ready dataset layer

Deliverables:

```text
structured_records.jsonl
baseline_span_candidates.jsonl
baseline_error_report.md
```

Mục tiêu: chuyển data assessment thành đầu vào trực tiếp cho solution chính.

---

# 14. Definition of Done

Bước data assessment được coi là đạt khi:

- Parse đủ 100 record.
- Có section/subsection inventory bao phủ phần lớn header phổ biến và có cơ chế xử lý unknown.
- Có line table giữ offset đúng.
- Có span_candidates cho cả 5 target type và auxiliary type.
- Có assertion trigger inventory với negation/historical/family rule được tách rõ.
- Có normalization inventory nhưng không làm hỏng raw offset.
- Có auxiliary non-target list để giảm false positive.
- Có review ít nhất 300-500 span theo stratified sampling.
- Có báo cáo lỗi nêu rõ false positive/false negative/ambiguity.
- Có seed dictionaries được derive từ reviewed spans, không phải từ phỏng đoán rời rạc.

## Kết luận

Data assessment nên tạo một lớp dữ liệu trung gian có thể tái sử dụng, không chỉ là danh sách thuật ngữ. Với dữ liệu hiện tại, trọng tâm không phải chỉ là gom bệnh/triệu chứng/thuốc, mà là:

```text
section-aware extraction
+ offset-safe normalization
+ span candidate review
+ strict assertion scope
+ auxiliary term filtering
+ mapping-ready normalized spans
```

Lớp này sẽ là nền tốt hơn cho solution chính so với việc train model hoặc viết rule trực tiếp trên raw text.
