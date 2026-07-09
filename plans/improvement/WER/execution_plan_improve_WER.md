# Execution Plan: Pattern A Recall-Collapse Fix (structural fallback extractor)

> Companion execution plan for [`proposal_pattern_A_recall_collapse.md`](proposal_pattern_A_recall_collapse.md), scoped to raise `text_score` per [`proposal_WER_improvement.md`](proposal_WER_improvement.md). Baseline to beat: **text_score = 0.1169** (silver, 20 files), span recall R=0.12 (TP=46, FP=182, FN=324).

## 0. Assessment summary (why this plan is sound)

Verified directly against the codebase (`src/rule_extractors.py`, `src/section_parser.py`, `src/merge.py`, `scripts/build_v0_outputs.py`), plus `input/7.txt` and `silver_test/output/7.json`:

- **Root cause confirmed correct.** `extract_symptom_candidates()` and `extract_diagnosis_candidates()` only produce candidates from `normalized_find_spans()` dictionary hits. Section gates (`SYMPTOM_SUBSECTIONS`, `DIAGNOSIS_SUBSECTIONS`) are evaluated only *after* a hit already exists, so they cannot explain zero-output files. File 7 has 22 gold entities; dictionary extraction recovers only 3 (`chóng mặt` x2, `ho`); the other 19 sit on clean bullet/key-value lines in correctly-classified subsections but use vocabulary absent from the seed CSVs.
- **Gaps found in the proposal that this plan closes:**
  1. §3A.2 Tier 1 allowlist omits `IMAGING_RESULT_SECTION`, even though the codebase's own `DIAGNOSIS_SUBSECTIONS` constant already includes it, and the proposal's own §5.2 pattern D cites an imaging-typed gold example (`"chụp cắt lớp vi tính mạch máu (ctma)"` → `TÊN_XÉT_NGHIỆM`). **Fix: add `IMAGING_RESULT_SECTION` to the Tier 1 allowlist.**
  2. §3.3's proposed merge-ranking change is likely unnecessary: `merge.py`'s existing `_rank()` already sorts by `(type_priority, -confidence, -span_len, start)`, and structural confidence (0.40) is always below any dictionary confidence (0.70-0.90+), so dictionary spans already win overlaps. Implement it anyway as a **cheap defensive tiebreak**, not a required fix.
  3. Tier 1/2 heuristic thresholds (verb-led-bullet exclusion list, 12-word cap on Tier 2 values) are reasonable starting points, not validated against data. Tune only if the post-rebuild rescore shows a precision regression — do not pre-optimize.

## 1. Implementation steps

### Step 1 — Add `extract_structural_candidates()` to `src/rule_extractors.py`

New constants (near existing `SYMPTOM_SUBSECTIONS` / `DIAGNOSIS_SUBSECTIONS` block):

```python
STRUCTURAL_SOURCE_TAG = ["structural_fallback"]
STRUCTURAL_CONFIDENCE = 0.40

# Tier 1: bullet-line harvest allowlist (concept-bearing subsections)
STRUCTURAL_BULLET_SECTIONS = {
    "CHRONIC_DISEASES": ENTITY_DIAGNOSIS,
    "CURRENT_SYMPTOMS": ENTITY_SYMPTOM,
    "DIAGNOSTIC_FINDINGS": ENTITY_DIAGNOSIS,
    "LAB_RESULT_SECTION": ENTITY_LAB_NAME,
    "IMAGING_RESULT_SECTION": ENTITY_LAB_NAME,   # gap-fix vs proposal §3A.2
    "ADMISSION_REASON": ENTITY_SYMPTOM,
}

# Tier 2: section-level key-value harvest allowlist
STRUCTURAL_KEY_VALUE_SECTIONS = {
    "ADMISSION_REASON": ENTITY_SYMPTOM,
    "CHRONIC_DISEASES": ENTITY_DIAGNOSIS,
    "DIAGNOSTIC_FINDINGS": ENTITY_DIAGNOSIS,
    "LAB_RESULT_SECTION": ENTITY_LAB_NAME,
    "IMAGING_RESULT_SECTION": ENTITY_LAB_NAME,
    "MEDICATION_HISTORY": ENTITY_DRUG,
    "MEDICATION_ADMINISTERED": ENTITY_DRUG,
}
# CURRENT_HISTORY section-level fallback -> ENTITY_SYMPTOM (handled separately,
# mirrors extract_symptom_candidates' existing `section_type == CURRENT_HISTORY` rule)

EVENT_VERB_PREFIXES = (
    "được", "bắt đầu", "lên lịch", "đã", "gọi", "đến", "sau đó",
)

SYMPTOM_DETAIL_QUALIFIER_STOPLIST = {
    normalize_for_matching(term) for term in (
        "Vị trí", "Mức độ nghiêm trọng", "Thời gian", "Tần suất", "Chiếu xạ",
        "Các yếu tố làm nặng thêm", "Các yếu tố làm giảm",
        "Các triệu chứng liên quan", "Lan tỏa",
        "Yếu tố làm nặng thêm", "Yếu tố làm giảm", "Triệu chứng kèm theo",
    )
}

STRUCTURAL_MAX_VALUE_WORDS = 12
```

Function signature and behavior:

```python
def extract_structural_candidates(
    doc: ClinicalDocument,
    non_target_terms: Sequence[str],
) -> List[SpanCandidate]:
    """Dictionary-free fallback: harvest concepts from bullet/key-value structure.

    Tier 1: bullet lines in STRUCTURAL_BULLET_SECTIONS -> split on ,/; -> candidate
            per fragment, skip event/action bullets (EVENT_VERB_PREFIXES).
    Tier 2: key_value lines whose *subsection* is in STRUCTURAL_KEY_VALUE_SECTIONS,
            or whose section_type == CURRENT_HISTORY (symptom fallback) -> harvest
            value_or_line_span(), strip trailing parenthetical, split on ,/;,
            cap at STRUCTURAL_MAX_VALUE_WORDS words, skip SYMPTOM_DETAIL qualifier
            rows via SYMPTOM_DETAIL_QUALIFIER_STOPLIST (match on normalized key).
    Tier 3: free_text lines -> explicitly out of scope, not emitted.

    All candidates: confidence=STRUCTURAL_CONFIDENCE, source=STRUCTURAL_SOURCE_TAG,
    trimmed via trim_span(), rejected if normalized text matches non_target_terms,
    and must pass validate_candidate_offsets() like every other extractor.
    """
```

Implementation notes:
- Reuse `trim_span()`, `value_or_line_span()`, `make_candidate()`, `normalize_for_matching()` — no new offset-mapping logic needed.
- Comma/semicolon split: split on `,` and `;` outside parentheses (simple regex is fine here since spans are already line-local; do not need full parenthesis-balancing given the short line lengths observed).
- Strip trailing parenthetical: `re.sub(r"\s*\([^)]*\)\s*$", "", text)` before offset-trimming — but the trim must still be done via raw offsets, so compute the raw span with the parenthetical, then binary-narrow the end offset by finding the last non-parenthetical char, not just regex on a copy of the string (to keep `doc.raw_text[start:end] == text` intact through `make_candidate()`).
- `LAB_RESULT_SECTION` / `IMAGING_RESULT_SECTION` bullets/values default to `ENTITY_LAB_NAME` (name-only, per proposal §3.1 item 3 and per `proposal_WER_improvement.md` §5.2 pattern D which calls out lab names as commonly name-only in gold).
- `CURRENT_HISTORY`-level (not just subsection-level) key_value lines follow the same rule already used by `extract_symptom_candidates()` (`line.section_type == "CURRENT_HISTORY"`), so a bullet/value outside the named subsections but inside `CURRENT_HISTORY` still yields `TRIỆU_CHỨNG`.

### Step 2 — Wire into `run_rule_extraction()` in `scripts/build_v0_outputs.py`

```python
from src.rule_extractors import (
    ...,
    extract_structural_candidates,
)

def run_rule_extraction(documents: list) -> tuple[list, dict]:
    ...
    for doc in documents:
        all_candidates.extend(extract_lab_candidates(doc, resources["lab_terms"]))
        all_candidates.extend(extract_drug_candidates(doc, resources["drug_terms"]))
        all_candidates.extend(extract_diagnosis_candidates(doc, resources["diagnosis_terms"], resources["non_target_terms"]))
        all_candidates.extend(extract_symptom_candidates(doc, resources["symptom_terms"]))
        all_candidates.extend(extract_structural_candidates(doc, resources["non_target_terms"]))  # NEW, after dictionary extractors
        all_candidates.extend(reject_non_target_candidates(doc, resources["non_target_terms"]))
    ...
```

Order matters only for readability here — `merge_candidates()` (Step 3) is what actually decides precedence, not insertion order. Both `build_v0_outputs.py` and `build_v0_linked_outputs.py` call this shared function, so no separate change needed in `build_v0_linked_outputs.py`.

### Step 3 — Defensive tiebreak in `src/merge.py`

```python
def _rank(candidate: SpanCandidate) -> Tuple[int, float, int, int, int]:
    """Lower tuple wins for overlap selection."""
    priority = TYPE_PRIORITY.get(candidate.type_candidate, 99)
    span_len = candidate.end - candidate.start
    is_structural = 1 if "structural_fallback" in candidate.source else 0
    return (priority, -candidate.confidence, is_structural, -span_len, candidate.start)
```

This is a no-op in practice (confidence ordering already achieves the same result) but makes the precedence explicit and future-proofs against a later confidence-tuning change that could otherwise let a structural span leak past a same-confidence dictionary span.

### Step 4 — Regression tests in `tests/test_rule_extractors.py`

Add tests following the existing `make_doc()` / `assert_offsets()` pattern:

1. `test_structural_bullet_harvest_symptom` — bullet line under `CURRENT_SYMPTOMS` with an out-of-dictionary term produces a `TRIỆU_CHỨNG` structural candidate with `confidence == 0.40` and `source == ["structural_fallback"]`.
2. `test_structural_comma_split` — a bullet like `- Không có sốt, đau ngực, chóng mặt` splits into separate candidates.
3. `test_structural_event_verb_bullet_dropped` — a bullet starting with `Được đưa đến Cấp cứu...` produces no candidate.
4. `test_structural_symptom_detail_stoplist` — a `SYMPTOM_DETAIL` key_value line `Vị trí: N/A` produces no candidate; a qualifier-free `SYMPTOM_DETAIL` row does.
5. `test_structural_yields_to_dictionary_on_overlap` — build a doc where a dictionary term and a structural span overlap the same range; run both extractors + `merge_candidates()`; assert only the dictionary-sourced entity survives.
6. `test_structural_imaging_section` — bullet/value under `IMAGING_RESULT_SECTION` produces `TÊN_XÉT_NGHIỆM` (covers the gap-fix from §0).

### Step 5 — Rebuild and rescore

```powershell
python scripts/build_v0_linked_outputs.py
python scripts/score_silver.py
```

Record before/after:
- Overall `text_score` vs baseline **0.1169**.
- Per-file span TP/FP/FN for files **2, 6, 7, 9, 13, 15, 17, 20** (the Pattern A files) from `reports/silver_eval.md`.
- Zero-empty-output check: none of the 8 files should have 0 predicted entities after the change (validation criterion from the proposal §7).
- No `offset_errors` introduced (`validate_candidate_offsets()` must accept all structural spans).

### Step 6 — Run full test suite; tune only if needed

```powershell
python -m pytest repo/ViClinicalIE/tests -q
```
(or the project's existing no-pytest runner pattern, e.g. `python tests/test_rule_extractors.py`, if that's how the suite is normally invoked — confirm against actual CI/test scripts before running.)

If precision regresses badly on the rescore (many new false positives), tune in this order before reverting the feature:
1. Tighten `EVENT_VERB_PREFIXES` (add more verbs observed in FP list).
2. Lower `STRUCTURAL_MAX_VALUE_WORDS`.
3. Narrow `STRUCTURAL_BULLET_SECTIONS`/`STRUCTURAL_KEY_VALUE_SECTIONS` allowlists if a specific subsection is the dominant FP source.

## 2. Validation criteria (from proposal §7, retained)

- No `offset_errors` introduced.
- Zero empty-output files among 2/6/7/9/13/15/17/20 after the change.
- Overall `text_score` non-decreasing versus baseline **0.1169**, with recall gains concentrated on the eight target files.

## 3. Out of scope (explicitly deferred)

- Tier 3 free-text/prose extraction (files 4, 8, and similar) — needs clause/NP segmentation, tracked as a future workstream per proposal §3A.2.
- Dictionary expansion (WS1 in `proposal_WER_improvement.md`) — complementary but separate effort.
- Type disambiguation (`CHẨN_ĐOÁN` vs `TRIỆU_CHỨNG`) — does not affect `text_score` (WER is text-only), deferred per `proposal_WER_improvement.md` §4.5/§7 WS5.
