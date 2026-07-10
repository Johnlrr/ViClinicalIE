# Kiến trúc Hybrid Rule-based + ViHealthBERT cho ViClinicalIE

## 1. Mục đích tài liệu

Tài liệu này đề xuất kiến trúc hệ thống cho bài toán ViClinicalIE, tập trung vào việc kết hợp:

- Encoder-based NER, ưu tiên ViHealthBERT.
- Rule-based và parser chuyên biệt.
- Dictionary và ontology linker cho ICD-10/RxNorm.
- Assertion detection cho phủ định, người nhà và tiền sử.

Mục tiêu là tận dụng khả năng hiểu ngữ cảnh và khái quát hóa của encoder, đồng thời giữ độ chính xác của rule trên các cấu trúc thuốc và xét nghiệm. Thiết kế phải phù hợp với văn bản y khoa free-form, không giả định input luôn có section hoặc template cố định.

Tài liệu ở mức kế hoạch kiến trúc, chưa mô tả chi tiết implementation của code base hiện tại.

---

## 2. Bài toán và mục tiêu tối ưu

Hệ thống nhận một văn bản y khoa tự do và phải trả về danh sách entity gồm:

- `text`: chuỗi xuất hiện nguyên văn trong input.
- `position`: character offset `[start, end]`.
- `type`: một trong năm loại entity.
- `assertions`: các thuộc tính ngữ cảnh áp dụng cho entity.
- `candidates`: mã ICD-10 hoặc RxNorm khi entity thuộc loại tương ứng.

Các loại entity:

```text
TRIỆU_CHỨNG
CHẨN_ĐOÁN
THUỐC
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
```

Metric cuối cùng:

```text
final_score = 0.3 × text_score
            + 0.3 × assertions_score
            + 0.4 × candidates_score
```

Các hệ quả kiến trúc quan trọng:

1. Không được tối ưu NER F1 một cách độc lập với assertion và linking.
2. Sai type bị phạt nặng vì có thể đồng thời tạo false positive và false negative.
3. Candidate mapping có trọng số cao nhất, vì vậy ICD/RxNorm phải tham gia vào quá trình đánh giá span/type, không chỉ là bước trang trí cuối pipeline.
4. Output thừa entity, assertion hoặc candidate đều có thể làm giảm Jaccard score.
5. Boundary phải bám nguyên văn và character offset phải được bảo toàn tuyệt đối.

---

## 3. Quyết định kiến trúc

### 3.1 Chọn kiến trúc hybrid

Kiến trúc đề xuất là:

```text
Rule-based structured parsers
             ┐
ViHealthBERT NER
             ├──> Type-aware candidate resolver
Dictionary   │                 │
ICD/RxNorm   ┘                 ▼
                          Canonical entities
                                │
                                ▼
                       Assertion detection
                                │
                                ▼
                    ICD/RxNorm final reranking
                                │
                                ▼
                    Offset/schema validation
                                │
                                ▼
                           JSON output
```

Rule và NER cùng sinh hypotheses. Hệ thống không dùng một thứ tự ưu tiên cứng áp dụng cho tất cả entity type. Một resolver theo type sẽ tổng hợp confidence, bằng chứng cấu trúc, ngữ cảnh và ontology để quyết định entity cuối.

### 3.2 Không dùng section như điều kiện bắt buộc

Input được mô tả là free-form. Vì vậy hệ thống không được giả định:

- Luôn có heading.
- Heading luôn được viết đúng chuẩn.
- Mỗi tài liệu có cùng danh sách section.
- Nội dung luôn nằm trong section đúng về mặt ngữ nghĩa.

Section detection, nếu có, chỉ là một nguồn bằng chứng mềm:

```text
candidate_score += section_or_context_evidence
```

Không dùng section như hard gate:

```text
candidate bị loại vì không nằm trong section mong đợi  # Không khuyến nghị
```

ViHealthBERT và các parser cục bộ phải vẫn hoạt động trên raw text khi không phát hiện được section nào.

### 3.3 Local structure quan trọng hơn global section

Thay vì cố phân loại toàn bộ tài liệu thành các section chủ quan, hệ thống ưu tiên nhận diện các vai trò cục bộ có thể quan sát trực tiếp:

- Heading-like line.
- Narrative sentence.
- Bullet hoặc numbered item.
- Medication-list item.
- Lab name-result pattern.
- Colon-separated field.
- Table-like row.
- Cue phrase gần entity.

Ví dụ:

```text
1. aspirin 81 mg po daily
```

Có thể gắn local role `medication_item` mà không cần kết luận rằng toàn bộ vùng văn bản là section `Medications`.

```text
WBC: 14,43; NEUT%: 76,4
```

Có thể gắn local role `lab_result_row` để hỗ trợ tách và ghép tên xét nghiệm với kết quả.

---

## 4. Nguyên tắc thiết kế

### 4.1 Raw-text first và bảo toàn offset

- Raw text là nguồn chuẩn duy nhất cho output.
- Không thay đổi text trước khi ghi offset cuối.
- Mọi normalization phải có mapping ngược về raw character offset.
- Trước khi output phải kiểm tra:

```python
raw_text[start:end] == entity_text
```

Nếu quy ước `end` của scorer là inclusive thay vì exclusive, toàn pipeline phải thống nhất theo đúng quy ước đó và có test round-trip tương ứng.

### 4.2 Candidate generation tách biệt candidate resolution

Extractor không cần tự quyết định entity cuối. Mỗi nhánh có thể sinh candidate cùng metadata:

```text
start
end
text
predicted_type
source
source_confidence
rule_id
local_role
context_features
dictionary_score
linker_score
```

Resolver sẽ chịu trách nhiệm:

- Chọn span.
- Chọn type.
- Giải quyết overlap.
- Gộp duplicate.
- Quyết định giữ hoặc loại candidate.

### 4.3 Threshold theo type và theo nguồn

Không dùng một confidence threshold chung cho mọi nhãn. Cần threshold riêng theo:

- Entity type.
- Nguồn candidate.
- Có hoặc không có bằng chứng từ dictionary/linker.
- Structured hoặc narrative context.

### 4.4 Precision trước các fallback rộng

Structural fallback không phải extractor ngang hàng với rule chính xác và encoder. Nó chỉ là last-resort candidate generator:

- Chạy khi các nguồn tốt hơn không tìm thấy entity phù hợp.
- Chỉ áp dụng trong local context phù hợp.
- Không tự động được output nếu thiếu bằng chứng xác nhận.
- Có threshold cao và giới hạn boundary.

---

## 5. Pipeline tổng thể

```text
Raw clinical text
        │
        ▼
Offset-preserving preprocessing
        │
        ├───────────────┬────────────────┬─────────────────┐
        ▼               ▼                ▼                 ▼
ViHealthBERT NER   Drug parser      Lab parser       Dictionary/rules
        │               │                │                 │
        └───────────────┴────────────────┴─────────────────┘
                                │
                                ▼
                Local structure/context annotator
                                │
                                ▼
                   Boundary composition/expansion
                                │
                                ▼
                    Preliminary ICD/RxNorm retrieval
                                │
                                ▼
                     Type-aware global resolver
                                │
                                ▼
                         Canonical entities
                                │
                                ▼
                       Assertion detection
                                │
                                ▼
                   Final candidate mapping/reranking
                                │
                                ▼
                 Offset, schema and consistency checks
                                │
                                ▼
                            JSON output
```

---

## 6. Các tầng xử lý

## 6.1 Offset-preserving preprocessing

> Trạng thái 2026-07-10: baseline đã triển khai và kiểm thử. Chi tiết thay đổi, API, giới hạn và test result xem tại [implementation log](offset_preserving_preprocessing_implementation.md).

Mục tiêu:

- Tạo các view phục vụ model và parser mà không làm mất raw offset.
- Tách sentence, line hoặc window cho tài liệu dài.
- Nhận diện dấu câu, bullet, delimiter và khoảng trắng.
- Chuẩn hóa phục vụ lookup nhưng luôn giữ offset map.

Các representation có thể gồm:

```text
raw_text
normalized_lookup_text
sentence_windows
line_windows
token_offsets
normalization_offset_map
```

Normalization chỉ dùng cho matching/linking, ví dụ:

- Lowercase.
- Chuẩn hóa Unicode.
- Chuẩn hóa khoảng trắng.
- Chuẩn hóa dấu phẩy/dấu chấm trong lookup.
- Bỏ dấu hoặc chuyển alias trong một số retriever.

Không được dùng normalized string để xuất `text` hoặc `position` trực tiếp.

## 6.2 ViHealthBERT NER

> Trạng thái 2026-07-10: inference layer offset-safe đã triển khai và kiểm thử. Module hiện hỗ trợ BIO/BIOES decoding, model-window offset mapping, overlap deduplication, threshold theo type và backend Hugging Face tùy chọn. Toàn bộ implementation, workflow, trace và ví dụ được hợp nhất tại [tài liệu ViHealthBERT NER](vihealthbert_ner.md).

### Vai trò chính

ViHealthBERT là semantic extractor chính cho:

```text
TRIỆU_CHỨNG
CHẨN_ĐOÁN
```

Nó cũng có thể sinh candidate cho:

```text
THUỐC
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
```

nhưng với ba loại có cấu trúc này, parser chuyên biệt giữ vai trò xác nhận hoặc xây boundary cuối.

### Backbone

Thứ tự thử nghiệm:

1. ViHealthBERT base-word.
2. ViHealthBERT base-syllable nếu tokenizer và offset alignment phù hợp.
3. PhoBERT base làm baseline đối chứng.

Không chọn model chỉ dựa trên domain pretraining; phải chọn theo dev score thực tế.

### Formulation

Baseline đề xuất:

```text
Token classification với BIOES
```

BIOES được ưu tiên hơn BIO nếu implementation ổn định, do biểu diễn boundary rõ hơn. BIO vẫn là fallback đơn giản.

Các nâng cấp chỉ thực hiện sau khi baseline được kiểm chứng:

- CRF decoding.
- Span classification.
- Multi-task NER + assertion.
- Ensemble nhiều encoder.

### Inference trên văn bản dài

- Chạy theo sentence hoặc sliding window có overlap.
- Mỗi window giữ offset về raw document.
- Candidate ở vùng overlap được deduplicate bằng resolver.
- Không cắt giữa entity nếu có thể tránh bằng sentence/line-aware windowing.

## 6.3 Drug parser

> Trạng thái 2026-07-10: baseline offset-safe đã triển khai và kiểm thử với **3 nguồn core seed**: curated dictionary (drug_aliases.csv), RxNorm/RXNCONSO catalog (IN/PIN/MIN/BN atoms), và ViHealthBERT NER candidate input. Module thực hiện core-seed deduplication theo priority dictionary > NER > RxNorm, boundary composition sang strength/dose/route/form/frequency/PRN, local-role soft evidence và optional preliminary RxNorm evidence. Toàn bộ implementation, workflow, trace và ví dụ được hợp nhất tại [tài liệu Drug parser](drug_parser.md).

### Mục tiêu

Nhận entity thuốc với boundary phù hợp schema, gồm các thành phần có thể xuất hiện:

```text
drug name
strength
dose
form
route
frequency
PRN marker
```

Ví dụ:

```text
amlodipine 10 mg po daily
```

Thiết kế không nên chỉ lựa chọn giữa span rule và span NER. Nên dùng composition:

```text
NER/dictionary nhận drug core
→ parser mở rộng sang strength/route/frequency
→ RxNorm linker kiểm tra representation
```

Drug candidate có confidence cao khi đồng thời có nhiều bằng chứng:

- Drug core nằm trong dictionary hoặc được NER nhận diện chắc chắn.
- Có strength/dose pattern hợp lệ.
- Có route/frequency marker.
- Nằm trong local role dạng medication item.
- Có RxNorm retrieval score tốt.

## 6.4 Lab parser

### Mục tiêu

Tách riêng:

- `TÊN_XÉT_NGHIỆM`.
- `KẾT_QUẢ_XÉT_NGHIỆM`.

Đồng thời duy trì quan hệ nội bộ name-result để tránh pairing sai.

Các pattern cần hỗ trợ:

```text
name: value
name = value unit
name (description): value
name value reference-range unit
nhiều cặp name-value trên cùng một dòng
table-like rows
```

Parser cần xử lý:

- Dấu phẩy hoặc dấu chấm thập phân.
- Phần trăm.
- Khoảng giá trị.
- Toán tử `<`, `>`, `≤`, `≥`.
- Đơn vị.
- Viết tắt xét nghiệm.
- Dấu phân cách `:`, `=`, `;`, tab hoặc nhiều khoảng trắng.

ViHealthBERT hỗ trợ nhận tên xét nghiệm trong prose hoặc ngoài dictionary, nhưng parser cục bộ là thành phần chính để xử lý cấu trúc tên-kết quả.

## 6.5 Dictionary và rule chính xác cao

Dictionary/rule có ba vai trò:

1. Sinh candidate chính xác cao.
2. Bổ sung feature cho NER candidate.
3. Hỗ trợ boundary/type resolution.

Nên phân loại rule theo reliability thay vì coi mọi rule ngang nhau:

```text
exact_catalog_match
exact_curated_alias
structured_pattern
contextual_dictionary_match
substring_match
structural_fallback
```

Mỗi loại có prior confidence riêng và được tune theo entity type.

Substring match phải thận trọng, nhất là với triệu chứng/chẩn đoán, vì có thể bắt một từ y khoa nằm trong cụm không phải target entity.

## 6.6 Local structure/context annotator

Đây không phải section parser bắt buộc. Tầng này chỉ gắn feature mềm cho candidate hoặc text window.

Feature ví dụ:

```text
is_heading_like
is_bullet_item
is_numbered_item
is_medication_like_line
is_lab_result_like_line
is_narrative_sentence
has_diagnosis_cue
has_history_cue
has_family_cue
has_negation_cue
optional_section_label
optional_section_confidence
```

Nếu phát hiện được heading/section đáng tin cậy, thông tin này được sử dụng như feature. Nếu không phát hiện được, candidate vẫn tiếp tục qua pipeline.

## 6.7 Boundary composition và expansion

Boundary resolver cục bộ thực hiện các phép biến đổi theo type:

### Thuốc

```text
drug core → full medication mention
```

### Xét nghiệm

```text
lab core → canonical lab-name span
numeric/value expression → result span
name ↔ result internal pairing
```

### Triệu chứng/chẩn đoán

- Ưu tiên boundary học từ NER.
- Loại cue không thuộc entity nếu annotation guideline không bao gồm cue.
- Không mặc định chọn span dài nhất.
- Dùng punctuation, conjunction và syntactic cues để tách list entity.

Ví dụ:

```text
Không có sốt, đau ngực, chóng mặt
```

phải tạo ba entity riêng nếu guideline yêu cầu như vậy, còn cue `Không có` được assertion detector xử lý.

## 6.8 Preliminary ICD/RxNorm retrieval

Linker chạy sơ bộ trước merge cho candidate thuộc loại:

```text
CHẨN_ĐOÁN
THUỐC
```

Kết quả retrieval được dùng làm feature:

```text
top1_score
topk_scores
exact_alias_match
normalized_match
contextual_match
catalog_coverage
```

Ví dụ:

- Drug candidate có structured pattern và RxNorm match mạnh: tăng confidence.
- Candidate được NER gán `THUỐC` nhưng không có medication context và không có RxNorm evidence: hạ confidence, nhưng không mặc định loại vì catalog có thể thiếu alias.
- Hai boundary thuốc cạnh tranh: ưu tiên boundary tạo representation/linking phù hợp hơn.
- Diagnosis candidate có ICD match tốt và cue chẩn đoán: tăng confidence.

Ontology evidence là tín hiệu hỗ trợ, không phải hard requirement tuyệt đối.

---

## 7. Type-aware candidate resolver

## 7.1 Mục tiêu

Resolver tạo danh sách entity canonical từ các candidate chồng lấn hoặc mâu thuẫn.

Không dùng precedence list cố định như:

```text
rule > NER > dictionary > fallback
```

cho toàn bộ hệ thống. Thay vào đó, mỗi candidate được chấm theo feature và entity type.

## 7.2 Score khái niệm

Một công thức khởi đầu:

```text
final_confidence =
    w_model       × calibrated_model_probability
  + w_rule        × rule_reliability
  + w_structure   × local_structure_score
  + w_context     × context_compatibility
  + w_dictionary  × dictionary_score
  + w_linker      × ontology_linker_score
  + w_boundary    × boundary_quality
  - w_overlap     × overlap_penalty
  - w_invalid     × invalid_span_penalty
```

Các trọng số phải khác nhau theo type. Ví dụ:

- `TRIỆU_CHỨNG`: trọng số model/context cao hơn structured rule.
- `THUỐC`: drug parser, dictionary và RxNorm evidence cao hơn.
- `KẾT_QUẢ_XÉT_NGHIỆM`: structured pattern cao hơn semantic model.

Giai đoạn đầu có thể dùng weighted heuristic. Sau khi có dev set đủ tốt, có thể học resolver bằng logistic regression, gradient boosting hoặc một classifier nhỏ trên candidate features.

## 7.3 Confidence calibration

Softmax token probability không mặc nhiên là confidence đã calibrated. Cần:

- Tune threshold riêng theo type.
- Tune threshold riêng theo source nếu cần.
- Dùng temperature scaling hoặc phương pháp calibration tương đương trên dev set.
- Đánh giá precision-recall curve thay vì chọn threshold tùy ý.

## 7.4 Chính sách overlap

### Cùng type

- Gộp duplicate exact span.
- Với containment, chọn span có score và boundary quality tốt hơn.
- Không mặc định chọn longest span.
- Với medication core nằm trong full medication mention, giữ full mention nếu đúng guideline.

### Khác type

- Không cho phép cùng span xuất ra nhiều type nếu guideline không hỗ trợ.
- Dùng context, local role và ontology evidence để quyết định type.
- Đặc biệt cẩn thận giữa `TRIỆU_CHỨNG` và `CHẨN_ĐOÁN`.

### Entity liền kề

- Không tự động merge chỉ vì khoảng cách ngắn.
- Dùng delimiter, conjunction và pattern theo type.

## 7.5 Chính sách ban đầu theo type

### `TRIỆU_CHỨNG`

```text
ViHealthBERT = extractor chính
dictionary/rule = bổ sung và xác nhận
structural fallback = last resort
```

### `CHẨN_ĐOÁN`

```text
ViHealthBERT semantics
+ diagnosis cue/context
+ ICD retrieval evidence
```

### `THUỐC`

```text
NER hoặc dictionary nhận drug core
+ medication parser mở rộng boundary
+ RxNorm evidence
```

### `TÊN_XÉT_NGHIỆM`

```text
lab parser/dictionary = nguồn chính trong structured text
ViHealthBERT = nguồn chính/bổ sung trong prose
```

### `KẾT_QUẢ_XÉT_NGHIỆM`

```text
lab parser = nguồn chính
NER = bằng chứng bổ sung
```

---

## 8. Assertion detection

Assertion được chạy sau khi đã có canonical entities để tránh gắn assertion vào candidate bị loại hoặc duplicate.

Các assertion:

```text
isNegated
isFamily
isHistorical
```

## 8.1 Kiến trúc assertion hybrid

```text
High-precision cue rules
          +
Entity-context encoder classifier
          +
Optional local/section evidence
          ↓
Assertion scope resolver
```

### Rule phù hợp với

- Cue rõ ràng: `không`, `chưa ghi nhận`, `phủ nhận`.
- Family terms: `bố`, `mẹ`, `anh`, `chị`, `gia đình`.
- Historical terms: `tiền sử`, `trước đây`, `đã từng`.

### Encoder classifier phù hợp với

- Scope phủ định trong câu liệt kê.
- Quan hệ xa giữa cue và entity.
- Câu có nhiều chủ thể.
- Phân biệt thuốc đang dùng với danh sách thuốc trước nhập viện.
- Ngữ cảnh temporal mơ hồ.

## 8.2 Section chỉ là evidence

Ví dụ heading `Tiền sử` có thể tăng xác suất `isHistorical`, nhưng không tự động gắn assertion nếu:

- Section detector confidence thấp.
- Entity thực tế nằm ngoài phạm vi heading.
- Có cue cục bộ mâu thuẫn.

Tương tự, không cần heading `Tiền sử gia đình` mới nhận được `isFamily`; family cue trong câu có thể đủ.

## 8.3 Scope resolution

Ví dụ:

```text
Không sốt, đau ngực hay khó thở.
```

Hệ thống phải xác định cue phủ định có scope trên toàn danh sách hay chỉ entity đầu. Window khoảng cách đơn giản là baseline, nhưng nên bổ sung:

- Punctuation boundary.
- Conjunction structure.
- Clause boundary.
- Entity order.
- Encoder context score.

---

## 9. Candidate mapping ICD-10 và RxNorm

## 9.1 Hai-stage linking

### Stage 1: retrieval

Sinh candidate bằng:

- Exact/normalized alias lookup.
- Curated mapping.
- Lexical fuzzy retrieval.
- Dense retrieval nếu có dữ liệu phù hợp.
- Context-aware retrieval/reranking.

### Stage 2: reranking

Xếp hạng bằng:

- Entity text.
- Expanded/normalized form.
- Câu hoặc window ngữ cảnh.
- Entity type.
- Drug strength/form nếu có.
- Diagnosis context.
- Retrieval score từ nhiều nguồn.

## 9.2 Candidate count policy

Jaccard phạt candidate dư thừa, nên không trả nhiều mã chỉ để tăng khả năng chứa đáp án.

Cần tune:

- Top-1 hay top-k theo type.
- Score threshold.
- Margin giữa candidate thứ nhất và thứ hai.
- Khi nào trả nhiều ICD code hợp lý.

Chính sách phải được chọn bằng end-to-end dev score, không chỉ Recall@k của retriever.

## 9.3 Feedback về resolver

Linking và extraction không cần train end-to-end ngay, nhưng linker evidence nên phản hồi về resolver:

```text
span/type candidates
       ↓
pre-linking evidence
       ↓
span/type resolution
       ↓
final reranking
```

Điều này đặc biệt quan trọng vì `candidates_score` chiếm 40% tổng điểm.

---

## 10. Dữ liệu huấn luyện

## 10.1 Thứ tự ưu tiên dữ liệu

```text
Manual-corrected real notes
> reviewed silver data
> high-confidence weak labels
> reviewed synthetic data
> unreviewed synthetic data
> structural fallback labels
```

Không trộn mọi nguồn với trọng số ngang nhau.

## 10.2 Manual annotation

Manual-corrected subset là nguồn dữ liệu quan trọng nhất. Nên chọn tài liệu đại diện cho:

- Narrative prose.
- Danh sách thuốc.
- Lab tables hoặc lab-like rows.
- Nhiều entity trên một câu.
- Phủ định.
- Tiền sử.
- Người nhà.
- Thuật ngữ tiếng Việt, tiếng Anh và viết tắt trộn lẫn.

Ưu tiên sửa case mà:

- Rule và NER bất đồng.
- Model confidence thấp.
- Span có nhiều cách chọn boundary.
- Linker không tìm được candidate.
- Type `TRIỆU_CHỨNG`/`CHẨN_ĐOÁN` dễ nhầm.

Đây là active-learning loop có giá trị cao hơn việc chỉ sinh synthetic ngẫu nhiên.

## 10.3 Weak labels

Mỗi weak label cần metadata:

```text
label_source
label_confidence
rule_id
was_reviewed
```

Chỉ dùng rule có precision cao để tạo weak label chính. Structural fallback labels phải:

- Bị loại khỏi train nếu quá noisy; hoặc
- Có sample weight thấp; hoặc
- Chỉ dùng làm unlabeled candidate cho human review.

## 10.4 Synthetic data

Synthetic data nên mô phỏng format thật:

- Prose không cấu trúc.
- Dòng viết tắt.
- Dấu câu và lỗi chính tả.
- Thuốc có hoặc không có strength/route/frequency.
- Xét nghiệm nhiều kiểu delimiter.
- Câu có phủ định, tiền sử và người nhà.

Synthetic data cần filter:

- Entity text phải xuất hiện nguyên văn.
- Offset round-trip hợp lệ.
- Type và assertion nhất quán.
- ICD/RxNorm candidate tồn tại trong resource cho phép.
- Không chứa template leakage quá rõ.

## 10.5 Training schedule

Khuyến nghị:

### Phase A — Weak/synthetic pre-fine-tuning

- Dùng dữ liệu lớn hơn nhưng có noise.
- Sample weighting theo nguồn.
- Không dùng dev/test gold trong phase này.

### Phase B — Gold/manual fine-tuning

- Fine-tune tiếp trên manual-corrected data.
- Early stopping theo end-to-end dev metrics và exact span/type F1.

### Phase C — Hard-example iteration

- Chạy inference trên unlabeled pool.
- Chọn các case bất đồng hoặc confidence thấp.
- Sửa nhãn thủ công.
- Fine-tune lại.

## 10.6 Chống leakage

- Chia train/dev theo document, không theo sentence ngẫu nhiên.
- Nếu synthetic sinh từ template, cùng template không được nằm ở cả train và dev.
- Deduplicate near-identical notes.
- Dev/test phải là annotation sạch, không dùng output rule làm ground truth.

---

## 11. Evaluation và ablation

## 11.1 Metric bắt buộc

- Official `text_score`.
- Official `assertions_score`.
- Official `candidates_score`.
- Official `final_score`.

## 11.2 Metric chẩn đoán

- Exact span + type precision/recall/F1.
- Per-type precision/recall/F1.
- Boundary-only F1.
- Type accuracy khi boundary đúng.
- Character-offset validity rate.
- Assertion F1/Jaccard theo từng assertion.
- ICD/RxNorm Recall@k và final Jaccard.
- False positives theo source.
- False negatives theo local role/document style.

## 11.3 Oracle experiments

Để xác định bottleneck:

1. Gold spans/types → assertion score.
2. Gold spans/types → candidate linking score.
3. Predicted spans/types → assertion score.
4. Predicted spans/types → candidate linking score.

Nếu gold span vẫn có linking score thấp, vấn đề nằm ở linker chứ không chỉ extraction.

## 11.4 Ablation bắt buộc

```text
A. Rule-only
B. NER-only
C. Rule + NER với precedence cứng
D. Rule + NER với type-aware resolver
E. D + local context features
F. E + preliminary linker evidence
G. F + assertion hybrid
```

Riêng section/context:

```text
1. Không dùng section/context
2. Hard section gating
3. Soft local/section features
```

Kỳ vọng là soft features tăng score mà không làm giảm recall mạnh. Hard section gating chỉ được giữ nếu thực nghiệm chứng minh tốt hơn rõ ràng trên dev set đa dạng.

---

## 12. Roadmap triển khai

## Milestone 0 — Annotation guideline và dev set sạch

### Công việc

- Chốt boundary guideline cho năm entity type.
- Chốt quy ước offset.
- Chốt khi nào medication span gồm dose/route/frequency.
- Chốt cách tách lab name và result.
- Sửa thủ công một dev set đại diện.

### Acceptance criteria

- 100% entity trong dev set pass offset round-trip.
- Hai người review thống nhất phần lớn các case boundary/type khó.
- Official scorer chạy được ổn định.

## Milestone 1 — Dataset builder

### Công việc

- Chuyển document + span annotation thành BIO/BIOES.
- Hỗ trợ subword alignment.
- Gắn metadata nguồn nhãn.
- Split theo document/source/template.

### Acceptance criteria

- Token labels map ngược đúng character span.
- Không có train/dev leakage đã biết.
- Có báo cáo label distribution theo type/source.

## Milestone 2 — ViHealthBERT baseline

### Công việc

- Fine-tune ViHealthBERT.
- So sánh word/syllable nếu khả thi.
- Chạy PhoBERT baseline.
- Tune threshold theo type.

### Acceptance criteria

- Có per-type F1 và exact span/type F1.
- Có raw prediction với confidence và offset.
- Chọn backbone dựa trên dev score.

## Milestone 3 — Structured parsers

### Công việc

- Drug-core detection và medication boundary expansion.
- Lab name/result/unit parser.
- Pairing nội bộ giữa tên xét nghiệm và kết quả.
- Local role detector.

### Acceptance criteria

- Test riêng trên medication-list và lab-table cases.
- Boundary đúng theo annotation guideline.
- Không phụ thuộc global section.

## Milestone 4 — Type-aware resolver

### Công việc

- Chuẩn hóa candidate schema.
- Deduplicate và overlap resolution.
- Weighted score theo type/source.
- Confidence calibration.
- Structural fallback trở thành last resort.

### Acceptance criteria

- Hybrid resolver tốt hơn rule-only và NER-only trên dev set.
- False positive từ structural fallback giảm rõ rệt.
- Không giảm precision mạnh ở thuốc/xét nghiệm.

## Milestone 5 — Linker feedback

### Công việc

- Preliminary ICD/RxNorm retrieval.
- Dùng linker score trong resolver.
- Final candidate reranking.
- Tune top-k/threshold theo Jaccard và final score.

### Acceptance criteria

- Candidate score tăng so với linking chỉ chạy sau merge.
- Candidate thừa giảm.
- Có báo cáo oracle linking.

## Milestone 6 — Assertion hybrid

### Công việc

- High-precision cue rules.
- Scope-aware assertion classifier.
- Dùng local context và optional section features.

### Acceptance criteria

- Assertion score tăng trên case liệt kê và câu nhiều chủ thể.
- Không phụ thuộc section detector để hoạt động.

## Milestone 7 — End-to-end tuning

### Công việc

- Tune entity thresholds.
- Tune resolver weights.
- Tune assertion thresholds.
- Tune candidate top-k.
- Error analysis theo nguồn/type/format.

### Acceptance criteria

- Hybrid tăng official final score trên dev set sạch.
- Pipeline deterministic ở inference.
- Output pass schema và offset validation.

---

## 13. Rủi ro và phương án giảm thiểu

## 13.1 Dữ liệu ít hoặc noisy

Rủi ro:

- Model overfit silver data.
- Học lại lỗi của rule từ weak labels.
- Synthetic data khác phân phối private test.

Giảm thiểu:

- Manual-corrected dev/train subset.
- Sample weighting theo nguồn.
- Weak pretraining rồi gold fine-tuning.
- Active learning trên model-rule disagreement.
- Kiểm tra theo document style.

## 13.2 Offset alignment sai

Rủi ro:

- Tokenizer subword.
- Unicode tiếng Việt.
- Normalization làm thay đổi độ dài.
- Sliding window overlap.

Giảm thiểu:

- Fast tokenizer có offset mapping khi khả dụng.
- Raw-to-normalized offset mapper.
- Round-trip validation bắt buộc.
- Unit test với dấu tiếng Việt, ký hiệu, tab và newline.

## 13.3 NER tăng recall nhưng giảm precision

Giảm thiểu:

- Threshold theo type.
- Confidence calibration.
- Resolver dùng context/dictionary/linker evidence.
- Không output structural fallback đơn độc.

## 13.4 Rule quá áp đảo model

Rủi ro:

- Precedence cứng giữ lại lỗi rule.
- NER không cải thiện được các vùng rule đã match sai.

Giảm thiểu:

- Candidate-level scoring.
- Rule reliability theo rule ID.
- Không coi mọi exact/substring match ngang nhau.
- Ablation precedence cứng so với resolver.

## 13.5 Section detection gây mất recall

Giảm thiểu:

- Section không phải prerequisite.
- Không hard gate entity bằng section.
- Local role/cue được ưu tiên.
- Missing section feature có giá trị trung tính.

## 13.6 Candidate explosion làm giảm Jaccard

Giảm thiểu:

- Resolver threshold cao hơn cho source noisy.
- Deduplicate trước linking.
- Tune top-k và score margin.
- Không trả candidate ontology không đủ bằng chứng.

---

## 14. Cấu hình baseline đề xuất

```text
Backbone:
  ViHealthBERT trước, PhoBERT làm đối chứng

NER task:
  BIOES token classification

Primary semantic types:
  TRIỆU_CHỨNG, CHẨN_ĐOÁN

Primary structured types:
  THUỐC, TÊN_XÉT_NGHIỆM, KẾT_QUẢ_XÉT_NGHIỆM

Candidate generation:
  ViHealthBERT + drug parser + lab parser + dictionary/rules

Context:
  Local role/cue features; section là optional soft feature

Merge:
  Type-aware candidate scoring, không precedence cứng toàn cục

Structural fallback:
  Last resort, cần bằng chứng bổ sung

Assertion:
  Cue rules trước; encoder scope classifier là bước nâng cấp

Linking:
  Preliminary retrieval làm resolver feature
  + final ICD/RxNorm reranking

Evaluation:
  Official scorer + exact span/type F1 + per-type diagnostics
```

---

## 15. Kết luận

Hybrid rule-based và ViHealthBERT là kiến trúc phù hợp cho ViClinicalIE, nhưng hiệu quả phụ thuộc vào cách phân vai và merge:

```text
ViHealthBERT
  = semantic extraction và generalization engine

Rule/parser
  = precision anchor cho thuốc và xét nghiệm có cấu trúc

Dictionary + ICD/RxNorm
  = candidate generation, validation và reranking evidence

Local context layer
  = soft evidence, không phải hard section dependency

Type-aware resolver
  = trọng tài quyết định span/type cuối

Assertion layer
  = xử lý scope ngữ cảnh trên canonical entities
```

Hệ thống không cần detect section mới có thể hoàn thiện. Thiết kế đúng cho free-form text là:

```text
raw extraction luôn hoạt động
+ local structure/context nếu quan sát được
+ optional section evidence nếu đủ tin cậy
```

Quyết định quan trọng nhất là không biến section parser hoặc precedence rule thành điểm lỗi duy nhất. Rule và encoder phải sinh bằng chứng song song; resolver theo từng type, có hỗ trợ từ ontology linker, mới quyết định entity cuối. Đây là kiến trúc cân bằng tốt nhất giữa precision, recall, khả năng generalize và metric end-to-end của bài toán.