# Phase 1 Data Requests V0

Generated from `V1_FROZEN` and the NER-1 GLiNER zero-shot reproduction. These
are targeted pilot requests, not sample-count quotas.

## Shared quality gate

- Use `data/golden/ANNOTATION_GUIDELINE_V2.md` and
  `data/golden/ner_data_schema.json` without branch-local semantic changes.
- Validate with `python scripts/validate_ner_dataset.py --input <file.jsonl>`.
- Preserve raw offsets and group clean/noisy variants by original sample.
- Submit a reviewed pilot before bulk generation.

## Person 2 — Problem NER

### P0: symptom precision and boundary contrasts

GLiNER development reproduction emitted 143 symptom predictions for 90 gold
symptoms, with exact F1 0.223 and relaxed F1 0.455. This indicates substantial
semantic overlap but poor precision/exact boundaries.

Create minimal contrasts for:

- symptom vs reporter/action/section-heading non-entities;
- cue-free span vs spans containing `không`, `bệnh nhân có`, or temporal cues;
- short core symptom vs clinically meaningful anatomy/severity modifiers;
- mixed Vietnamese/English symptoms and no-diacritic variants;
- repeated mentions in different sections.

### P0: symptom/diagnosis type contrast

Create paired templates that hold context constant while changing a
manifestation into a named disease conclusion. Include ambiguous Vietnamese
problem phrases, diagnostic triggers, suspected/ruled-out wording, and hard
negative disease-like noun phrases.

## Person 3 — Structured NER

### P0: test-result extraction

This is the largest gap. V1 exact result F1 was 0.0; GLiNER development exact
result F1 remained 0.0 and relaxed F1 was 0.054.

Create paired test/result examples for:

- `<test>: <value>`, `<test> là <value>`, and whitespace-only separators;
- value plus unit/range;
- decimal comma and decimal point;
- `âm tính`, `dương tính`, `bình thường`, `tăng`, and `giảm`;
- `từ v1 lên v2`;
- multiple analytes/results on one line;
- hard-negative bare numbers without a test anchor.

### P0: full medication formulation boundary

GLiNER drug relaxed recall was high (0.833) but exact F1 was 0.222, indicating
name discovery without the gold formulation boundary.

Create name-to-full-formulation contrasts covering strength, unit,
concentration, form, route, frequency, PRN, combination products, and stop
phrases such as `điều trị`. Include food/substance and section-heading hard
negatives (for example generic `thuốc`, caffeine context, tobacco context).

### P1: test name vs result and imaging finding

Create same-surface and near-surface contrasts for test names, qualitative
results, imaging procedures, descriptive findings, and explicit diagnostic
conclusions.

## Feedback loop

```text
pilot JSONL
→ shared validator
→ cross-review by the other data owner
→ NER-1/NER-2 benchmark on target error bucket
→ keep/reject/version decision
```