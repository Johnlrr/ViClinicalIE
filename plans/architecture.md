Tổng hợp nghiên cứu online về cách xây hệ thống này, và đề xuất kiến trúc.

## Những gì đã tìm được (research)

**Bài toán này thực chất là 4 sub-task NLP kinh điển ghép lại**, mỗi cái đều có literature/tooling riêng:

1. **Clinical NER** (phát hiện + phân loại khái niệm: triệu chứng/xét nghiệm/kết quả/chẩn đoán/thuốc)
   - Hướng truyền thống: spaCy/scispaCy (`en_core_sci_md`, AbbreviationDetector) hoặc MedCAT (CogStack) — pipeline NER + linking tích hợp, nhưng chủ yếu train cho tiếng Anh (MIMIC-III, UMLS, SNOMED).
   - Hướng LLM: fine-tune LLM nhỏ (≤9B theo ràng buộc đề bài) làm sequence labeling hoặc structured extraction (input free text → output JSON list). Tìm thấy nhiều model trên HuggingFace đã đi hướng này cho tiếng Việt, ví dụ `PeterPaker123/Qwen2.5-7B-Vietnamese-Medical-NER` (SFT + GRPO), `hoangkhang1628/vihealthbert-crf-medical-ner` (BERT+CRF classic).
   - Cho tiếng Việt: `ViHealthBERT` (demdecuong/vihealthbert-base-word, base-syllable) là pretrained encoder y khoa tiếng Việt duy nhất phổ biến — phù hợp làm backbone cho token classification (BIO tagging) vì đề bài yêu cầu vị trí ký tự chính xác (`position`), việc này hợp với span-based NER hơn là LLM sinh text tự do (LLM dễ lệch span/gây WER cao nếu tự paraphrase).

2. **Assertion / Context detection** (`isNegated`, `isFamily`, `isHistorical`)
   - Đây đúng là bài toán **ConText algorithm** (Chapman et al.) / **NegEx** — thuật toán rule-based kinh điển dùng "trigger terms" (phủ định: "không", "chưa", "loại trừ"; họ hàng: "bố", "mẹ", "người nhà"; tiền sử: "tiền sử", "đã từng") kèm scope window quanh khái niệm đích.
   - Triển khai tham khảo: `medspacy.context` (spaCy pipeline component implement ConText, hỗ trợ multi-language rule injection) — có thể viết rule set tiếng Việt riêng theo mô hình này thay vì dùng rule tiếng Anh có sẵn.
   - Đây là hướng rẻ, giải thích được, và vì metric là Jaccard trên tập nhãn assertion (không phải accuracy end-to-end phức tạp) nên rule-based có thể đạt điểm tốt mà không cần train riêng.

3. **Entity Linking / Candidate mapping** (ICD-10 cho bệnh, RxNorm cho thuốc)
   - **RxNorm**: NLM cung cấp REST API free (`RxNorm APIs` — `approximateTerm`, `findRxcuiByString`, `getApproximateMatch`) và **RxTerms API** (`clinicaltables.nlm.nih.gov/api/rxterms`) hỗ trợ autocomplete/fuzzy match tên thuốc → rxcui. Đã test trực tiếp, ví dụ `terms=amlodipine` trả về danh sách match ngay. Đây là nguồn ground truth để build local RxNorm dictionary (tên thuốc + liều + rxcui) offline, vì thi đấu **không được gọi API ngoài lúc inference** — phải tải toàn bộ RxNorm/ICD-10 dataset về offline và làm retrieval cục bộ (BM25/fuzzy string hoặc embedding).
   - **ICD-10-CM**: tương tự, NLM Clinical Table Search Service (`clinicaltables.nlm.nih.gov/api/icd10cm`) cho search theo code/name, dùng để build bộ dữ liệu ICD-10 offline (mã + tên bệnh) — nhưng đây là ICD-10-CM (tiếng Anh, US). Với văn bản tiếng Việt cần thêm bước dịch/ánh xạ tên bệnh tiếng Việt ↔ tên bệnh chuẩn ICD-10 (WHO ICD-10 hoặc bản dịch tiếng Việt của Bộ Y Tế) trước khi tra cứu.
   - Kỹ thuật linking chuẩn: **SapBERT** (Cambridge, self-alignment pretraining) — encoder sinh embedding cho cụm từ y khoa để so khớp gần nhất với entity trong KB bằng cosine similarity (dense retrieval), đây là phương pháp state-of-the-art cho biomedical entity linking, có bản cross-lingual (`SapBERT-UMLS-2020AB-all-lang-from-XLMR`) hỗ trợ nhiều ngôn ngữ non-English, phù hợp hướng: encode câu tiếng Việt trích ra → so khớp với embedding tên bệnh/thuốc tiếng Anh trong ICD-10/RxNorm (cross-lingual retrieval) mà không cần dịch riêng.
   - Vì đề cho phép **nhiều candidate** (list mã), nên kiến trúc hợp lý là: retrieval top-K bằng embedding/BM25 rồi optionally rerank bằng cross-encoder hoặc LLM nhỏ.

4. **LLM constraint đặc biệt của đề**: nếu dùng LLM/agent, self-host model ≤9B, không API ngoài. Điều này loại các API RxNorm/ICD online lúc submit — phải đóng gói dữ liệu ICD-10 + RxNorm thành file/db local đi kèm source code.

## Kiến trúc hệ thống đề xuất (end-to-end pipeline)

```
Input free text
     │
     ▼
[1] Preprocessing: sentence/clause split, abbreviation expansion (đơn vị đo, viết tắt y khoa VN)
     │
     ▼
[2] Concept Extraction (NER, span-based)
     - Backbone: ViHealthBERT hoặc PhoBERT fine-tuned token classification (BIO/BIOES)
       nhãn: TRIỆU_CHỨNG / TÊN_XÉT_NGHIỆM / KẾT_QUẢ_XÉT_NGHIỆM / CHẨN_ĐOÁN / THUỐC
     - Rule-based bổ trợ: regex cho pattern thuốc (tên + liều + đơn vị + dạng dùng),
       pattern xét nghiệm: kết quả (số + đơn vị đi liền tên xét nghiệm)
     - Output: list span (text, start, end, type)
     │
     ▼
[3] Assertion/Context detection (rule-based, ConText-style cho tiếng Việt)
     - Trigger dictionary: negation ("không", "chưa thấy", "loại trừ"...),
       family ("bố", "mẹ", "anh/chị/em", "người nhà"...),
       historical ("tiền sử", "đã từng", "từ trước", "trước đó")
     - Scope: window theo câu/dấu câu, có thể học thêm scope bằng dependency parse (VnCoreNLP/underthesea)
     - Chỉ áp dụng cho CHẨN_ĐOÁN, THUỐC, TRIỆU_CHỨNG theo đề
     │
     ▼
[4] Entity Linking / Candidate mapping (chỉ cho CHẨN_ĐOÁN, THUỐC)
     - Local KB: ICD-10 (mã+tên bệnh, có bản dịch tiếng Việt nếu có) 
                 RxNorm (rxcui + tên thuốc + liều + dạng bào chế, ưu tiên SCD/SBD term types)
     - Retrieval: BM25/fuzzy match (tên chuẩn hoá) + dense embedding (SapBERT cross-lingual 
       hoặc fine-tune trên cặp tên-Việt/tên-Anh) → top-K candidates
     - Optional rerank bằng cross-encoder hoặc LLM nhỏ để lọc candidate cuối
     │
     ▼
[5] Assemble output JSON theo đúng schema (text, position, type, assertions, candidates)
```

## Về mặt dữ liệu training thêm (silver/synthetic)
Vì đề cho phép "sử dụng giải pháp ngoài lời giải chính để tạo thêm dữ liệu huấn luyện", hướng khả thi:
- Dùng LLM lớn (chỉ để tạo data offline, không phải lúc inference) sinh thêm câu tiếng Việt có cấu trúc tương tự ví dụ đề cho, gán nhãn tự động rồi review/sửa.
- Kết hợp corpus MIMIC-III (tiếng Anh) dịch máy sang tiếng Việt để mở rộng vốn từ y khoa, hoặc dùng ViHealthBERT’s pretraining corpus.
- Áp dụng self-training: model v0 (rule + weak NER) generate silver labels trên phần lớn text, sau đó fine-tune model chính.

## Rủi ro / điểm cần quyết định
- Backbone NER: ViHealthBERT (nhỏ, encoder, rẻ để fine-tune, giữ span chính xác) **hay** LLM sinh JSON trực tiếp (dễ làm nhưng khó giữ đúng vị trí ký tự/character span → ảnh hưởng WER và cả pipeline vì computed trên "text" field). Khuyến nghị: encoder-based span extraction cho bước NER, LLM nhỏ (nếu dùng) chỉ hỗ trợ ở bước linking/rerank.
- Nguồn ICD-10 tiếng Việt: cần xác nhận có bản dịch chính thức nào khả dụng hay phải tự xây mapping tên bệnh Việt→Anh.

Đây là plan nghiên cứu tổng thể — sẵn sàng để bạn phản hồi hướng nào ưu tiên (rule-heavy nhanh chóng vs. train model heavy hơn) trước khi tôi bắt đầu implement.