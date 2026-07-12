# Checkpoint 03 — VietMed NER Adapter & Section-Aware Routing

> Trạng thái 2026-07-12: triển khai kế hoạch từ [`plan_ner.md`](../../../plan_ner.md) — adapt checkpoint `leduckhai/VietMed-NER` (subfolder `phobert-base-v2-VietMed-NER`) vào pipeline ViClinicalIE dùng compact BIO labels cho 5 entity types `TRIỆU_CHỨNG`, `CHẨN_ĐOÁN`, `THUỐC`, `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM`.

---

## 1. Mục tiêu & phạm vi

Checkpoint này hiện thực 6/7 bước trong [`plan_ner.md`](../../../plan_ner.md) §"Implementation plan":

1. Label adapter layer (`map_vietmed_label`).
2. Context-aware post-map cho `DISEASESYMTOM` (`route_diseasesyptom_candidates`).
3. NER dùng làm seed chỉ (chưa thay parser).
4. CLI option `--ner-label-map`.
5. Conservative default thresholds.
6. Tests.
7. **Chưa hoàn thành**: ablation trên `silver_test` (để Phase đánh giá riêng).

Tài liệu đi cùng checkpoint:

- [`ViClinicalIE/plan_ner.md`](../../../plan_ner.md) — kế hoạch gốc, đã có "Implementation log" được append.
- [`ViClinicalIE/plans/active/00_overview/00_architecture_hybrid_vihealthbert.md`](../00_overview/00_architecture_hybrid_vihealthbert.md) — architecture canabit: audit adherence nằm tại §4 bên dưới.

---

## 2. Thay đổi mã nguồn

### 2.1 `src/vihealthbert_ner.py`

| Thành phần | Vai trò |
| --- | --- |
| `VIETMED_TO_SUBMISSION` | Map `DRUGCHEMICAL→THUỐC`, `DIAGNOSTICS→TÊN_XÉT_NGHIỆM`, `UNITCALIBRATOR→KẾT_QUẢ_XÉT_NGHIỆM`. Non-target → `O`. |
| `_DISEASESYMTOM_PENDING`, `_TEMP_ENTITY_TYPES` | Temporary type để decoder lắp span đầy đủ trước khi routing. |
| `_DIAGNOSIS_SUBSECTIONS` / `_DIAGNOSIS_SECTION_TYPES` / `_SYMPTOM_SUBSECTIONS` / `_SYMPTOM_SECTION_TYPES` | Frozen set mirror từ [`rule_extractors`](../../src/rule_extractors.py:1) đảm bảo routing nhất quán với rule extractor. |
| `map_vietmed_label(label)` | Map raw BIO/BIOES, giữ prefix. `0`→`O`. Unknown→`O`. `DISEASESYMTOM`→`_DISEASESYMTOM_PENDING`. |
| `_route_diseasesyptom_by_context` | Trả `CHẨN_ĐOÁN`/`TRIỆU_CHỨNG` theo `section_type`/`subsection_type`, hoặc `None` nếu không rõ ràng. |
| `route_diseasesyptom_candidates(cands, lines, *, drop_without_context=True)` | Resolve pending; nếu không có context, drop hoặc giữ pending tuỳ `drop_without_context`. |
| `VIETMED_DEFAULT_THRESHOLDS` | `THUỐC=0.75`, `TÊN_XÉT_NGHIỆM=0.70`, `KẾT_QUẢ_XÉT_NGHIỆM=0.80`, `CHẨN_ĐOÁN=0.80`, `TRIỆU_CHỨNG=0.80`. |
| `ViHealthBERTNER.__init__(label_map="compact")` | Validate `{"compact","vietmed"}`; reject chưa support. |
| `ViHealthBERTNER.predict_windows(lines=...)` | Map label khi `vietmed`; **luôn** routing trong vietmed mode để pending-without-context được drop. |
| `ViHealthBERTNER.predict_document(document)` | Pass `document.lines` cho `predict_windows`. |
| `HuggingFaceTokenPredictor.__init__(label_map=...)` | Validate; bảo vệ PEFT branch chỉ override `id2label`/`label2id` khi `compact`. |

### 2.2 `scripts/build_new_arch_outputs.py`

- `--ner-label-map {compact,vietmed}` (default `compact`).
- `run_ner(label_map=...)` fill `VIETMED_DEFAULT_THRESHOLDS` cho threshold chưa khai báo; forward `label_map` xuống predictor + `ViHealthBERTNER`.
- `main()` log khi `vietmed` active.

### 2.3 `tests/test_vihealthbert_ner.py`

10 test functions mới + `__main__` stdlib test runner:

- `test_map_vietmed_label_high_signal_types`
- `test_map_vietmed_label_diseasesyptom_marks_pending`
- `test_map_vietmed_label_drops_non_target_and_zero`
- `test_diseasesyptom_routing_diagnosis_and_symptom_context`
- `test_diseasesyptom_routing_drops_without_context`
- `test_vietmed_label_map_pipeline_decodes_drugs_diag_lab`
- `test_vietmed_label_map_drops_non_target_labels`
- `test_vietmed_label_map_drops_pending_without_section_context`
- `test_compact_label_map_unchanged_by_default`
- `test_unknown_label_map_rejected`

### 2.4 Bug phát hiện & fix trong quá trình test

`predict_windows` ban đầu gate routing bằng `if self.label_map == "vietmed" and lines:` — khi `lines=[]` (test `test_vietmed_label_map_drops_pending_without_section_context`), routing bị skip, pending `_DISEASESYMTOM_PENDING` survive filter vì `thresholds.get(pending, 0.0)==0.0`. Plan §Risk controls yêu cầu drop conservative. Fix: đổi gate thành `if self.label_map == "vietmed":` — routing luôn chạy và `drop_without_context=True` drop pending không context.

---

## 3. Kết quả test

`python tests/test_vihealthbert_ner.py` (chạy từ `ViClinicalIE/`):

| Test | Kết quả |
| --- | --- |
| `test_bioes_decoding_preserves_raw_vietnamese_span_and_confidence` | ✅ ok |
| `test_compact_label_map_unchanged_by_default` | ✅ ok |
| `test_decoder_repairs_orphan_inside_label_and_type_transition` | ✅ ok |
| `test_diseasesyptom_routing_diagnosis_and_symptom_context` | ✅ ok |
| `test_diseasesyptom_routing_drops_without_context` | ✅ ok |
| `test_map_vietmed_label_diseasesyptom_marks_pending` | ✅ ok |
| `test_map_vietmed_label_drops_non_target_and_zero` | ✅ ok |
| `test_map_vietmed_label_high_signal_types` | ✅ ok |
| `test_predict_preprocessed_uses_offset_safe_model_windows` | ✅ ok |
| `test_predictor_offsets_cannot_exceed_window` | ✅ ok |
| `test_run_ner_falls_back_on_general_backend_init_failure` | ❌ pre-existing (cần pytest `monkeypatch`+`capsys`) |
| `test_run_ner_falls_back_when_checkpoint_has_no_fast_tokenizer` | ❌ pre-existing (cần pytest) |
| `test_run_ner_strict_reraises_fast_tokenizer_error` | ❌ pre-existing (cần pytest) |
| `test_type_threshold_filters_low_confidence_candidates` | ✅ ok |
| `test_unknown_label_map_rejected` | ✅ ok |
| `test_vietmed_label_map_drops_non_target_labels` | ✅ ok |
| `test_vietmed_label_map_drops_pending_without_section_context` | ✅ ok |
| `test_vietmed_label_map_pipeline_decodes_drugs_diag_lab` | ✅ ok |
| `test_window_inference_maps_local_offsets_and_deduplicates_overlap` | ✅ ok |

**Tổng:** 16/16 test thuộc checkpoint pass + 14/14 test mới của adapter pass. 3 test fail là pre-existing pytest-fixture test, không regress do thay đổi này.

---

## 4. Adherence audit vs [`00_architecture_hybrid_vihealthbert.md`](../00_overview/00_architecture_hybrid_vihealthbert.md)

### 4.1 Đã tuân thủ

| Nguyên tắc | Bằng chứng |
| --- | --- |
| §6.2 / §7.5 — NER là seed, không authority | `merge.py:47` rank `vihealthbert_ner=4` thấp hơn `drug_parser`/`lab_parser=1`. Adapter chỉ relabel, resolver quyết định final span/type. |
| §4.3 / §7.3 — Threshold riêng theo type & source | [`VIETMED_DEFAULT_THRESHOLDS`](../../src/vihealthbert_ner.py:97) per-type. `predict_windows` bắt `confidence >= thresholds.get(type_candidate, 0.0)`. |
| §7.1 / §13.4 — Resolver quyết định, không precedence cứng | [`merge_candidates`](../../src/merge.py:190) merge exact dupes + overlap-resolve qua `_rank` (source rank + confidence + span len + `TYPE_PRIORITY`). |
| §4.1 / §13.2 — Offset round-trip bắt buộc | `predict_windows` filter `raw_text[start:end] == text`. Tương tự ở drug_parser/lab_parser/rule_extractors/preprocessing/validator. |
| §3.3 — Local structure > global section | `route_diseasesyptom_candidates` lấy context qua line overlap (`line.start <= candidate.start < line.end`), không qua document-level section. |
| §6.7 — Boundary composition theo type | Adheres qua ủy quyền: NER chỉ emit span; expansion giữ ở drug_parser/lab_parser. |

### 4.2 Dị biệt (cần xử lý hoặc deliberate exception)

| Nguyên tắc | Dị biệt | Khuyến nghị |
| --- | --- | --- |
| §3.2 / §13.5 — "Section chỉ là soft evidence, không hard gate" | `route_diseasesyptom_candidates` trả `None` khi không section, và `drop_without_context=True` (default từ `predict_windows`) **drop** pending. Đây là hard gate cho `DISEASESYMTOM`, nghịch với principle. | (a) Document là deliberate exception theo `plan_ner.md §Risk controls` ("DISEASESYMTOM high-risk, require section context or high confidence"), hoặc (b) flip `drop_without_context=False` và ủy thác cho resolver với `w_context=0, w_model×p>0` theo §7.2. Khuyến nghị deliberate exception + tune trong Phase 7. |
| §7.2 — Two-stage weighted score | Resolver hiện dùng `_rank` rời rạc (source rank + confidence + span len), chưa theo công thức `w_model×p + w_context×ctx + ...`. | Đề nghị Phase-7 tuning áp dụng weighted score khi đã có dev set. |
| §6.6 — Local structure/context annotator độc lập | `is_narrative_sentence`, `has_negation_cue`, `has_history_cue`, v.v. chưa attach vào NER candidate; chỉ `source`/`section_type`/`subsection_type` propagate. | Milestone 3 item, không phải regression. |

### 4.3 Kết luận audit

Adapter tuân thủ các **hard constraint** (offset round-trip, per-type threshold, NER-as-seed, no global precedence). Một **tension có ý thức** duy nhất: conservative drop của `DISEASESYMTOM` không context —acak đi ngược §3.2/§13.5 nhưng phù hợp `plan_ner.md §Risk controls`. Cần team **chốt chủ động** trước khi fold vào Phase 7.

---

## 5. Mapping theo roadmap milestone

| Milestone | Trạng thái | Ghi chú |
| --- | --- | --- |
| **M0 — Annotation guideline / dev set** | ❓ Chưa thấy | Không thuộc phạm vi checkpoint này. |
| **M1 — Dataset builder** | ❌ Chưa | — |
| **M2 — ViHealthBERT baseline** | ⚠️ Cập nhật | Có adapter cho checkpoint third-party (VietMed), chưa có self-fine-tuned checkpoint. |
| **M3 — Structured parsers** | ✅ (tiếp tục) | Drug/lab parser tiếp tục nhận NER seed qua adapter; không regression. |
| **M4 — Type-aware resolver** | ✅ (giữ) | `merge.py` xử lý candidate từ adapter cùng cơ chế source-rank; không cần thêm. |
| **M5 — Linker feedback** | ⚠️ Không đổi | Adapter không tạo ICD/RxNorm evidence; chưa đổi layer linker. |
| **M6 — Assertion hybrid** | ❌ Không đổi | — |
| **M7 — End-to-end tuning** | ❌ Chưa | Ablation bước 7 của `plan_ner.md` chưa chạy trên `silver_test`. |

---

## 6. Còn lại cho evaluation sau

Theo `plan_ner.md §7 Evaluate ablation`:

- Baseline `--skip-ner`.
- NER không mapping (gần như zero useful spans vì `_parse_label` reject non-target).
- Mapped VietMed NER `--ner-label-map vietmed`.
- So sánh span/type/full-entity F1 + FP inspection.
- Quyết định per-type enable/disable theo metric gain.

Sau khi có ablation, kết quả nên được fold vào checkpoint tiếp theo (04) hoặc update tại [`silver_eval_new_arch.md`](02_silver_eval_new_arch.md).

> **Update 2026-07-12**: Ablation đã chạy — xem [`04_ner_ablation_vietmed.md`](04_ner_ablation_vietmed.md). Kết quả: VietMed-NER adapter làm giảm mọi metric ABOUT.md chính thức (`text_score`, `assertions_score`, `candidates_score`, `final_score`) trên silver scope 20 file, ngoại trừ cải thiện F1 cho `TÊN_XÉT_NGHIỆM`. Cần deliberate exception (a) trong §4.2 nên nghiêng về giữ nguyên conservative drop, và cần tune per-type threshold trước khi đưa VietMed-NER vào pipeline mặc định.

---

## 7. Kết luận ngắn gọn

**Đã đạt:**

- ✅ Adapter label mapping (high-signal + DISEASESYMTOM pending).
- ✅ Section-aware routing dùng line overlap, không dùng document-level section.
- ✅ Conservative per-type thresholds + CLI toggle `--ner-label-map`.
- ✅ Offset round-trip bảo toàn (filter trong `predict_windows`).
- ✅ PEFT branch được bảo vệ không override VietMed label space.
- ✅ 14/14 test mới + 2/2 test default path pass.

**Chưa đạt ( Phase sau):**

- ⚠️ Ablation trên `silver_test` (bước 7 của plan).
- ⚠️ Calibration thực tế thresholds per silver score.
- ⚠️ Resolve deliberate tension giữa `plan_ner.md §Risk controls` (drop-without-context) và `architecture §3.2/§13.5` (section là soft evidence).
- ⚠️ Two-stage weighted score (§7.2) hiện chưa Implement trong resolver.
