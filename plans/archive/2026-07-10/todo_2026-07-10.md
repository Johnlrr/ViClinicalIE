Dưới đây là **bản trình bày đề xuất hướng C: xây NER model-based bằng ViHealthBERT/PhoBERT** cho hệ thống ViClinicalIE. Nội dung này ở mức proposal/slide, **chưa implement gì**.

---

# Đề xuất hướng C: Nâng cấp Concept Extraction bằng Encoder-based NER

## 1. Vấn đề hiện tại

Hệ thống hiện tại là **rule-based + dictionary-based V0**.

Pipeline hiện tại:

```text
Input text
  → section_parser
  → rule_extractors / structural fallback
  → assertion rules
  → merge
  → ICD/RxNorm linker
  → JSON output
```

Điểm mạnh:

- Deterministic, dễ debug.
- Không cần dữ liệu training ban đầu.
- Tốt với pattern có cấu trúc rõ như thuốc, xét nghiệm, liều lượng, đơn vị.

Nhưng điểm yếu lớn:

- Phụ thuộc mạnh vào seed dictionary.
- Gặp concept lạ là miss.
- Structural fallback tăng recall nhưng kéo precision xuống.
- Free-text/prose extraction còn yếu.
- Không generalize tốt sang private test.

Kết quả hiện tại trên silver test:

- Span+type F1 khoảng **0.21**.
- `TRIỆU_CHỨNG` nhiều false positive.
- `TÊN_XÉT_NGHIỆM` gần như hỏng hoàn toàn.
- Assertion và candidate linking bị kéo theo vì span đầu vào chưa tốt.

**Kết luận:** bottleneck chính là bước **Concept Extraction**.

---

## 2. Mục tiêu của hướng C

Thay vì chỉ mở rộng rule/dictionary, ta bổ sung một mô hình **NER encoder-based** để học cách nhận diện concept từ ngữ cảnh.

Mục tiêu:

1. Tăng recall với concept ngoài dictionary.
2. Giảm false positive do structural fallback quá rộng.
3. Giữ span chính xác theo character offset.
4. Tạo nền tảng tốt hơn cho assertion detection và entity linking.
5. Vẫn giữ rule-based như safety net cho pattern thuốc/xét nghiệm.

---

## 3. Tại sao không dùng LLM sinh JSON trực tiếp?

Có thể dùng LLM nhỏ ≤9B, nhưng với bài này rủi ro cao:

- LLM dễ paraphrase text.
- Dễ lệch `start/end position`.
- Dễ sinh entity không tồn tại nguyên văn.
- Khó đảm bảo schema và offset chính xác.
- Inference chậm và khó kiểm soát.

Trong khi đó, encoder NER dạng BIO tagging phù hợp hơn:

```text
Bệnh nhân đau ngực và khó thở
O       O     B-TRIỆU_CHỨNG I-TRIỆU_CHỨNG O B-TRIỆU_CHỨNG
```

Ưu điểm:

- Dự đoán trực tiếp trên token/span.
- Dễ map về character offset.
- Nhẹ, nhanh, self-host được.
- Phù hợp với ràng buộc competition.

**Khuyến nghị:** dùng **ViHealthBERT hoặc PhoBERT fine-tuned token classification**, không dùng LLM JSON làm extractor chính.

---

## 4. Backbone đề xuất

### Option 1 — ViHealthBERT

Phù hợp nhất vì pretrained trên miền y khoa tiếng Việt.

Candidate:

```text
ViHealthBERT base-word / base-syllable
```

Ưu điểm:

- Domain-specific clinical Vietnamese.
- Có khả năng hiểu thuật ngữ y khoa tốt hơn PhoBERT thường.
- Nhỏ, inference được offline.

Nhược điểm:

- Cần kiểm tra tokenizer và alignment character offset.
- Có thể ít ecosystem hơn PhoBERT.

### Option 2 — PhoBERT

Ưu điểm:

- Mạnh cho tiếng Việt tổng quát.
- Tooling phổ biến.
- Dễ fine-tune.

Nhược điểm:

- Không chuyên domain y khoa.
- Có thể miss thuật ngữ chuyên ngành.

### Đề xuất chọn

Ưu tiên:

```text
ViHealthBERT → nếu setup/tokenizer ổn
PhoBERT → fallback nếu ViHealthBERT khó tích hợp
```

---

## 5. Nhãn NER cần train

Theo architecture hiện tại, các entity type gồm:

```text
CHẨN_ĐOÁN
THUỐC
TRIỆU_CHỨNG
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
```

Dạng BIO:

```text
B-CHẨN_ĐOÁN
I-CHẨN_ĐOÁN
B-THUỐC
I-THUỐC
B-TRIỆU_CHỨNG
I-TRIỆU_CHỨNG
B-TÊN_XÉT_NGHIỆM
I-TÊN_XÉT_NGHIỆM
B-KẾT_QUẢ_XÉT_NGHIỆM
I-KẾT_QUẢ_XÉT_NGHIỆM
O
```

Có thể cân nhắc BIOES nếu muốn span boundary tốt hơn, nhưng BIO đơn giản hơn cho giai đoạn đầu.

---

## 6. Dữ liệu training lấy từ đâu?

Hiện chưa có gold thật lớn, nên dùng chiến lược bootstrap:

### Nguồn 1 — Silver data hiện tại

Dùng `silver_test/output/*.json` làm dữ liệu nhãn ban đầu.

Ưu điểm:

- Có sẵn schema gần giống output thật.
- Có text/span/type/assertion/candidates.

Nhược điểm:

- Silver có noise vì được tạo bằng GPT.
- Chỉ 20 file, quá nhỏ nếu dùng một mình.

### Nguồn 2 — V0 rule output làm weak label

Chạy pipeline hiện tại trên `input/*.txt`, lấy các span có confidence cao làm weak labels.

Ví dụ:

- Dictionary exact drug/lab: tin cậy cao.
- Curated diagnosis/symptom dictionary: tin cậy trung bình.
- Structural fallback: tin cậy thấp, cần lọc kỹ.

### Nguồn 3 — Synthetic clinical notes

Dùng LLM lớn offline để sinh thêm câu y khoa tiếng Việt và annotation JSON.

Lưu ý:

- Chỉ dùng để tạo dữ liệu training offline.
- Không dùng API ngoài lúc inference.
- Cần review hoặc filter để tránh hallucination.

### Nguồn 4 — Manual correction nhỏ nhưng chất lượng cao

Chọn 30–50 file/case representative, sửa nhãn thủ công.

Đây là nguồn giá trị nhất để fine-tune/validate.

---

## 7. Chiến lược training đề xuất

Không nên train ngay từ dữ liệu noisy toàn bộ. Nên đi theo 3 phase.

### Phase 1 — Dataset conversion

Chuyển JSON span output thành token-level BIO labels.

Input:

```json
{
  "text": "Bệnh nhân đau ngực và khó thở",
  "entities": [
    {"text": "đau ngực", "start": 10, "end": 18, "type": "TRIỆU_CHỨNG"},
    {"text": "khó thở", "start": 22, "end": 29, "type": "TRIỆU_CHỨNG"}
  ]
}
```

Output token labels:

```text
Bệnh       O
nhân       O
đau        B-TRIỆU_CHỨNG
ngực       I-TRIỆU_CHỨNG
và         O
khó        B-TRIỆU_CHỨNG
thở        I-TRIỆU_CHỨNG
```

Cần đặc biệt chú ý:

- Offset mapping raw text ↔ normalized text.
- Tokenizer subword alignment.
- Các span overlap hoặc duplicate.

### Phase 2 — Fine-tune baseline NER

Train model token classification với dữ liệu silver + weak labels đã lọc.

Evaluation:

- Entity exact-match F1.
- Per-type precision/recall/F1.
- Character span exact match.
- WER text_score theo scorer hiện tại.

### Phase 3 — Hybrid inference

Không thay rule-based hoàn toàn. Dùng hybrid:

```text
NER model output
  + high-precision rule output for drug/lab patterns
  + merge resolver
  → assertion/linking/output
```

Vai trò:

- NER model: bắt concept ngữ nghĩa mở như triệu chứng/chẩn đoán/free-text.
- Rule-based: bắt structured pattern như thuốc + liều, xét nghiệm + đơn vị.
- Merge: chọn span tốt nhất khi overlap.

---

## 8. Cách kết hợp NER model với rule hiện tại

Đề xuất không phá hệ thống V0, mà thêm một nhánh mới:

```text
Input document
   │
   ├── Rule extractors hiện tại
   │       ├── lab pattern
   │       ├── drug pattern
   │       ├── dictionary diagnosis/symptom
   │       └── structural fallback
   │
   ├── NER model extractor mới
   │       └── ViHealthBERT/PhoBERT token classification
   │
   ▼
merge_candidates()
   │
   ▼
assertion → linking → output
```

Quy tắc merge đề xuất:

1. Drug/lab structured rule thắng nếu pattern rõ ràng.
2. NER thắng structural fallback nếu overlap.
3. Dictionary exact có thể ngang hoặc cao hơn NER tùy confidence.
4. Với symptom/diagnosis free-text, ưu tiên NER nếu confidence đủ cao.
5. Structural fallback chỉ giữ vai trò recall safety net khi model/rule không bắt gì.

Rank gợi ý:

```text
high_precision_rule_drug/lab
> NER high confidence
> dictionary diagnosis/symptom
> NER medium confidence
> structural fallback
```

---

## 9. Vì sao hướng này giải quyết đúng bottleneck?

Hiện tại lỗi chính không phải vì pipeline thiếu bước, mà vì **span extractor không hiểu ngữ cảnh**.

Ví dụ các lỗi hiện tại:

- Out-of-dictionary concept → rule miss.
- Dòng bullet dài → structural fallback bắt quá rộng.
- Free-text paragraph → rule không biết cắt cụm.
- Symptom detail row → dễ sinh FP.

NER model học được các pattern như:

```text
"Cảm thấy mệt mỏi nhiều khi gắng sức trong tuần qua"
→ một span triệu chứng dài

"Không có sốt, đau ngực, chóng mặt"
→ ba span triệu chứng riêng

"Rối loạn cảm xúc (trầm cảm)"
→ chẩn đoán
```

Đây là những thứ rule phải viết rất nhiều ngoại lệ mới xử lý được.

---

## 10. Rủi ro của hướng C

### Rủi ro 1 — Dữ liệu ít/noisy

Nếu chỉ dùng 20 silver files, model dễ overfit.

Giảm rủi ro:

- Kết hợp weak labels từ rule.
- Sinh synthetic data.
- Manual correction một tập nhỏ chất lượng cao.
- Dùng cross-validation.

### Rủi ro 2 — Offset alignment sai

Token classification dùng tokenizer subword; output phải map về character offset.

Giảm rủi ro:

- Dùng fast tokenizer nếu có offset_mapping.
- Test kỹ trên tiếng Việt có dấu.
- So sánh `doc.raw_text[start:end] == predicted_text` trước khi output.

### Rủi ro 3 — Model tăng recall nhưng giảm precision

Giảm rủi ro:

- Dùng confidence threshold theo type.
- Calibrate threshold trên silver validation.
- Merge với rule high-precision.

### Rủi ro 4 — Domain mismatch

Synthetic data có thể không giống note thật.

Giảm rủi ro:

- Sinh data theo format các file input hiện tại.
- Mix synthetic với real silver.
- Manual review một phần.

---

## 11. Roadmap đề xuất

### Milestone 1 — NER dataset builder

Mục tiêu:

- Chuyển `input/*.txt` + JSON annotation thành BIO dataset.
- Validate offset round-trip.

Deliverables:

```text
scripts/build_ner_dataset.py
training_data/ner/train.jsonl
training_data/ner/valid.jsonl
```

### Milestone 2 — Train baseline ViHealthBERT/PhoBERT

Mục tiêu:

- Fine-tune token classification.
- Xuất model local.

Deliverables:

```text
models/ner_vihealthbert_v1/
reports/ner_eval_v1.md
```

### Milestone 3 — Add NER extractor vào pipeline

Mục tiêu:

- Tạo `src/ner_extractor.py`.
- Convert model predictions thành `SpanCandidate`.
- Gắn source: `ner_vihealthbert`.

Không thay rule cũ, chỉ thêm nhánh.

### Milestone 4 — Hybrid merge tuning

Mục tiêu:

- Tune confidence/rank.
- So sánh:

```text
V0 rule-only
vs
NER-only
vs
Hybrid rule + NER
```

Metric:

- text_score.
- span/type F1.
- per-type F1.
- assertion/candidate downstream impact.

### Milestone 5 — Data iteration

Mục tiêu:

- Error analysis FN/FP.
- Add manual corrected data.
- Add synthetic examples for weak types: lab name/result, free-text symptoms, diagnosis.

---

## 12. Kết quả kỳ vọng

Ngắn hạn sau baseline NER:

- Recall tăng ở `CHẨN_ĐOÁN` và `TRIỆU_CHỨNG`.
- Free-text/prose files tốt hơn structural fallback.
- Giảm phụ thuộc dictionary.

Sau hybrid tuning:

- Giữ precision của rule cho thuốc/xét nghiệm.
- Tăng recall của model cho triệu chứng/chẩn đoán.
- `text_score` và span F1 cải thiện rõ hơn so với chỉ vá rule.

Kỳ vọng thực tế:

```text
Rule-only V0:       ổn định nhưng trần thấp
NER-only:           recall tốt hơn nhưng có thể noise
Hybrid rule + NER:  hướng cân bằng tốt nhất
```

---

## 13. Đề xuất quyết định kỹ thuật

Tôi đề xuất chọn hướng triển khai như sau:

```text
Backbone: ViHealthBERT trước, PhoBERT fallback
Task: token classification BIO
Inference: hybrid, không thay rule cũ
Training data: silver + weak labels + synthetic + manual corrected subset
Merge: high-precision rule > NER > structural fallback
Evaluation: scorer hiện tại + entity exact-match F1
```

---

## 14. Kết luận

Hướng C là hướng nâng trần hệ thống.

Rule-based hiện tại vẫn hữu ích, nhưng không nên là extractor chính lâu dài. Nên chuyển hệ thống sang kiến trúc hybrid:

```text
Rule-based = precision anchor
NER model = recall/generalization engine
Merge layer = arbitration
Assertion/linking = downstream enrichment
```

Đây là hướng phù hợp nhất nếu mục tiêu là cải thiện trên private test, nơi vocabulary và cách diễn đạt sẽ khác silver set hiện tại.