# Proposal: Fixing Pattern A — Whole-Document Recall Collapses

> **Scope:** Targeted fix for the "Pattern A" files identified in [`proposal_WER_improvement.md`](proposal_WER_improvement.md:173) §5.2 — files 2, 6, 7, 9, 13, 15, 17, 20, where the pipeline extracts almost nothing. These files are the single largest source of word-level deletions and therefore the highest-value recall lever.

## 1. The original hypothesis was wrong

The Pattern A note in [`proposal_WER_improvement.md`](proposal_WER_improvement.md:174) states these collapses are "most likely section detection failing so the section gates (§4.2) suppress everything." Direct inspection of the parser output disproves this.

Section detection is working correctly for all eight files. Evidence:

- [`analysis/record_stats.csv`](../../../ViClinicalIE/analysis/record_stats.csv:1): files 2, 6, 7, 9, 13, 17, 20 all report `detected_main_sections = CURRENT_HISTORY|HOSPITAL_ASSESSMENT|PAST_HISTORY`. File 15 reports `CURRENT_HISTORY|HOSPITAL_ASSESSMENT`, which is correct because [`input/15.txt`](../../../ViClinicalIE/input/15.txt:1) genuinely has no past-history block.
- [`analysis/section_inventory.csv`](../../../ViClinicalIE/analysis/section_inventory.csv:1): every one of these files parses its subsections (`CHRONIC_DISEASES`, `CURRENT_SYMPTOMS`, `DIAGNOSTIC_FINDINGS`, `LAB_RESULT_SECTION`, etc.) at confidence 1.0 with correct alias sources.

So the section gates in [`extract_symptom_candidates()`](../../../ViClinicalIE/src/rule_extractors.py:410) and [`extract_diagnosis_candidates()`](../../../ViClinicalIE/src/rule_extractors.py:353) are firing on correctly-labelled lines. The collapse happens one layer deeper.

## 2. Actual root cause: dictionary coverage

Every extractor only fires on terms present in the seed CSVs. When a correctly-sectioned line contains no dictionary term, nothing is emitted — regardless of the gates.

### Evidence — file 7

Gold [`silver_test/output/7.json`](../../../ViClinicalIE/silver_test/output/7.json:1) has 22 entities. Our prediction [`outputs/v0_linked/output/7.json`](../../../ViClinicalIE/outputs/v0_linked/output/7.json:1) has 3: `chóng mặt` (×2) and `ho`. Those three are exactly the terms present in [`symptom_seed_terms.csv`](../../../ViClinicalIE/data_resources/symptom_seed_terms.csv:1).

Everything missed is absent from the dictionaries, even though it sits on clean bullet / key-value lines inside correctly-detected subsections:

- `hội chứng nghiện rượu`, `tự tử`, `lú lẫn`, `khó nhìn gần`, `rối loạn thị giác`, `ảo giác thị giác`, `Ảo thanh` — under `CURRENT_SYMPTOMS`
- `Rối loạn cảm xúc (trầm cảm)` — under `CHRONIC_DISEASES`
- `bệnh lý chất trắng`, `Bệnh đa xơ cứng`, `các băng nhóm oligoclonal` — under `DIAGNOSTIC_FINDINGS`

None appear in [`symptom_seed_terms.csv`](../../../ViClinicalIE/data_resources/symptom_seed_terms.csv:1) (23 terms) or [`diagnosis_seed_terms.csv`](../../../ViClinicalIE/data_resources/diagnosis_seed_terms.csv:1) (23 terms).

### Evidence — file 9

[`input/9.txt`](../../../ViClinicalIE/input/9.txt:1) is dominated by out-of-dictionary concepts: `u cơ trơn tử cung`, `chảy máu nhiều`, `lower abdominal pain`, `huyết cầu tố`. The pipeline emits nothing for it (no `9.json` in [`outputs/v0_linked/output/`](../../../ViClinicalIE/outputs/v0_linked/output/)).

### Why these eight files specifically

They are not special in structure — they are special in vocabulary. Files that happen to use common seed terms (`đau ngực`, `khó thở`, `tăng huyết áp`) score acceptably under the identical section logic. The eight Pattern A files are dominated by rare, out-of-dictionary concepts, so a dictionary-only extractor collapses on them.

**Consequence:** loosening or removing the section gates alone changes nothing for these files, because there is no dictionary hit to un-gate. This is confirmed as recall limitation #1 in [`proposal_WER_improvement.md`](proposal_WER_improvement.md:99) §4.1.

## 3. Proposed fix: structural, dictionary-free fallback extractor

The highest-value lever is to extract concepts from the document's **structure** rather than only from dictionary membership. These notes are highly regular: target concepts live on bullet lines (`- ...`) and as the value of key-value lines (`key: value`) inside the clinical subsections. Those spans can be harvested directly.

### 3.1 New extractor in [`rule_extractors.py`](../../../ViClinicalIE/src/rule_extractors.py:1)

Add `extract_structural_candidates(doc, non_target_terms)` that:

1. Iterates `doc.lines`, selecting lines whose `line_kind` is `bullet` or `key_value` (from [`classify_line()`](../../../ViClinicalIE/src/section_parser.py:229)); skips `header` / `subheader` / empty lines.
2. Computes the span with [`value_or_line_span()`](../../../ViClinicalIE/src/rule_extractors.py:214) (value part for key-value, whole bullet body otherwise) and tightens it with [`trim_span()`](../../../ViClinicalIE/src/rule_extractors.py:106) so offsets stay exact and pass [`validate_candidate_offsets()`](../../../ViClinicalIE/src/rule_extractors.py:449).
3. Assigns a provisional type from the containing section:
   - symptom subsections (`ADMISSION_REASON`, `CURRENT_SYMPTOMS`, `SYMPTOM_DETAIL`, `IMMEDIATE_PRE_ADMISSION_STATUS`) or `section_type == CURRENT_HISTORY` → `TRIỆU_CHỨNG`
   - `CHRONIC_DISEASES` / `DIAGNOSTIC_FINDINGS` → `CHẨN_ĐOÁN`
   - `LAB_RESULT_SECTION` → `TÊN_XÉT_NGHIỆM` (value → `KẾT_QUẢ_XÉT_NGHIỆM` where a `VALUE_PATTERN` match exists)
   - `MEDICATION_HISTORY` / `MEDICATION_ADMINISTERED` → `THUỐC`
4. Uses a low confidence (≈0.40) with a distinct source tag (e.g. `["structural_fallback"]`) so any dictionary hit always outranks it.
5. Drops spans whose normalized text is in the non-target list (reuse logic from [`reject_non_target_candidates()`](../../../ViClinicalIE/src/rule_extractors.py:315)) so procedure/imaging method names don't leak in.

### 3.2 Wire into the run

Append the new extractor in [`run_rule_extraction()`](../../../ViClinicalIE/scripts/build_v0_outputs.py:40) after the dictionary extractors so it participates in dedupe/merge.

### 3.3 Merge ranking

Update [`_rank()`](../../../ViClinicalIE/src/merge.py:33) / [`merge_candidates()`](../../../ViClinicalIE/src/merge.py:45) so structural spans yield to any overlapping dictionary span (dictionary wins on both confidence and source), but survive where nothing else fired. The existing confidence-based ordering already achieves most of this via the 0.40 confidence; add an explicit source tiebreak so a structural span never displaces an equal-range dictionary span.

## 3A. Structural detection design (data-grounded refinement of §3.1)

The uniform "harvest every `bullet` or `key_value` line" rule in §3.1 is too blunt. Cross-referencing the parsed [`line_inventory.csv`](../../../ViClinicalIE/analysis/line_inventory.csv:1) against the silver gold for files 1–20 shows the rule is right for concept lists but wrong for two other line populations it would sweep up. The refinement below keeps the recall win on files 7/9 while avoiding a large false-positive flood on files like 3.

### 3A.1 Evidence

- **Whole-line harvest works for concept-list bullets.** In [`3.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:75) the `CHRONIC_DISEASES` bullets (lines 6–8) map one-to-one to gold `bệnh tim mạch do xơ vữa động mạch`, `tăng huyết áp`, `phình động mạch chủ nhỏ`. In [`7.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:307) the `CURRENT_SYMPTOMS` bullets (lines 11–17) map to the gold symptom concepts. For these, the bullet body is the concept.
- **Whole-line harvest floods false positives on `SYMPTOM_DETAIL` attribute rows.** [`3.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:107) lines 38–114 are dozens of `key_value` rows such as `Vị trí: N/A`, `Thời gian: 30 giây`, `Tần suất: N/A`, `Chiếu xạ: N/A`. **Gold extracts none of these.** A blind harvest emits ~50 junk spans from this one file — each an insertion under word-level WER.
- **Gold sub-segments lines that the harvest would keep whole.** Comma lists are split ([`16.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:541) line 30 `Không có sốt, đau ngực, chóng mặt, đánh trống ngực.` → four concepts), parentheticals and trailing noise are stripped, and a single line can mix types ([`7.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:299) line 3 `ho Rối loạn cảm xúc (trầm cảm) (tiền sử ...)` → `ho` as `TRIỆU_CHỨNG` plus `Rối loạn cảm xúc (trầm cảm)` as `CHẨN_ĐOÁN`, dropping the trailing parenthetical).
- **Some files are free-text-dominant, so the fallback no-ops on them.** [`8.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:342) is entirely prose (`free_text` lines 2–6) yet gold has 3+ concepts; [`4.txt`](../../../ViClinicalIE/analysis/line_inventory.csv:216) lines 7–11 are prose paragraphs with gold concepts. A bullet/key_value-only harvest recovers nothing here.

### 3A.2 Three-tier extractor

Replace the single §3.1 step-1 filter with three tiers, all emitted at low confidence (~0.40, source `["structural_fallback"]`) so any dictionary hit outranks them via §3.3.

**Tier 1 — list-bullet harvest (high precision).** For `bullet` lines whose subsection is in a concept-bearing allowlist — `CHRONIC_DISEASES`, `CURRENT_SYMPTOMS`, `DIAGNOSTIC_FINDINGS`, `LAB_RESULT_SECTION`, `ADMISSION_REASON` — harvest the bullet body, split on commas/semicolons into separate candidates, and drop event/action bullets led by a verb such as `Được`, `Bắt đầu`, `Lên lịch`, `Đã`, `Gọi`, `Đến`, `Sau đó`.

**Tier 2 — section-value harvest (medium precision).** For section-level `key_value` lines (e.g. `Lý do nhập viện:`, `Triệu chứng hiện tại:`), harvest the value with [`value_or_line_span()`](../../../ViClinicalIE/src/rule_extractors.py:214), strip trailing parentheticals, split comma/semicolon lists, and cap span length (e.g. reject values longer than ~12 words) so long prose values do not inject many insertion errors. **Exclude** `SYMPTOM_DETAIL` qualifier rows via the stoplist in §3A.3.

**Tier 3 — free-text (deferred).** Files with a high `free_text` ratio (see §3A.4) hold their concepts in prose, which needs clause/noun-phrase segmentation rather than line harvest. This is explicitly **out of scope** for this proposal; the residual recall gap on prose-dominant files (4, 8, and similar in the private test) is tracked as a known limitation, not addressed here.

### 3A.3 SYMPTOM_DETAIL qualifier stoplist

Within `SYMPTOM_DETAIL`, suppress any `key_value` row whose normalized key matches a known qualifier so the attribute grid (`N/A`, `30 giây`, `Chân`, `Ngực`, ...) never reaches output:

```
Vị trí, Mức độ nghiêm trọng, Thời gian, Tần suất, Chiếu xạ,
Các yếu tố làm nặng thêm, Các yếu tố làm giảm, Các triệu chứng liên quan,
Lan tỏa, Yếu tố làm nặng thêm, Yếu tố làm giảm, Triệu chứng kèm theo
```

Match on the normalized key (case/diacritic-insensitive, matching [`normalize_for_matching()`](../../../ViClinicalIE/src/normalization.py:1)) so casing variants like `các yếu tố làm nặng thêm` are also caught. The bare `SYMPTOM_DETAIL` concept-name rows (e.g. `- ngất xỉu:` with an empty value) are harvested by Tier 1 on the key, not the value.

### 3A.4 Free-text-ratio guard and metric

For each file, compute `free_text_ratio = free_text_lines / non_empty_lines` from [`line_inventory.csv`](../../../ViClinicalIE/analysis/line_inventory.csv:1). Use it two ways:

- **Guard:** the structural fallback self-limits to structured lines, so no guard is needed for safety — but log the ratio so prose-dominant files are visibly flagged as unaddressed by Tiers 1–2.
- **Metric:** report the mean `free_text_ratio` of files that still produce zero output after the change, to size the Tier 3 opportunity for a later workstream.

## 4. Expected impact and trade-off

- File 7: recovers the seven symptom bullets plus the diagnosis-section lines — roughly +12 spans toward the 22 gold.
- File 9: recovers the two symptom bullets and the chronic-disease value where currently zero are produced.
- Generalizes to all files without hand-expanding dictionaries.

Trade-off: structural extraction raises false positives (some bullets are events or procedures, not target concepts). Under the confirmed word-level WER metric ([`proposal_WER_improvement.md`](proposal_WER_improvement.md:70) §2.1), recall deletions dominate and each false-positive word is only a single insertion, so the expected net is positive. This must be **measured, not assumed** — see §6.

## 5. Alternatives considered

- **Loosen section gates only** — rejected: no dictionary hit exists to un-gate on these files, so it recovers nothing.
- **Expand seed dictionaries** — helps but does not scale; the private test will contain unseen vocabulary. Structural extraction is vocabulary-independent and complementary.

## 6. Implementation plan

1. Add `extract_structural_candidates()` to [`rule_extractors.py`](../../../ViClinicalIE/src/rule_extractors.py:1) per §3.1.
2. Wire it into [`run_rule_extraction()`](../../../ViClinicalIE/scripts/build_v0_outputs.py:40) after the dictionary extractors.
3. Adjust [`merge.py`](../../../ViClinicalIE/src/merge.py:45) ranking so structural spans yield to overlapping dictionary spans but survive in isolation.
4. Rebuild via [`build_v0_linked_outputs.py`](../../../ViClinicalIE/scripts/build_v0_linked_outputs.py:1); re-score with [`score_silver.py`](../../../ViClinicalIE/scripts/score_silver.py:1). Record before/after per-file TP/FP/FN on files 2/6/7/9/13/15/17/20 and the overall `text_score`.
5. If precision drops too far, add light structural filters (minimum length, drop event-verb-led bullets such as those beginning `Được`, `Bắt đầu`, `Lên lịch`) rather than reintroducing gates.
6. Add tests in [`tests/test_rule_extractors.py`](../../../ViClinicalIE/tests/test_rule_extractors.py:1) covering the fallback and its overlap interaction with dictionary hits.

## 7. Validation criteria

- No `offset_errors` introduced (all structural spans must round-trip through [`validate_candidate_offsets()`](../../../ViClinicalIE/src/rule_extractors.py:449)).
- Zero empty-output files among 2/6/7/9/13/15/17/20 after the change.
- Overall `text_score` from [`score_silver.py`](../../../ViClinicalIE/scripts/score_silver.py:1) is non-decreasing versus the WS0 baseline (0.1169), with recall gains concentrated on the eight target files.
