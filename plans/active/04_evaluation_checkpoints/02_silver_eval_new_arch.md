# Silver Test Evaluation — Active New Architecture

Date: 2026-07-11

## Scope

Evaluated the active new-architecture pipeline on the 20 files available in `silver_test/output`.

Command used:

```powershell
python scripts\build_new_arch_outputs.py --only 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20 --outputs-dir outputs\new_arch_silver_eval --analysis-dir analysis\new_arch_silver_eval
python scripts\score_silver.py --pred-dir outputs\new_arch_silver_eval\output --report-md reports\silver_eval_new_arch_scoped.md --report-json reports\silver_eval_new_arch_scoped.json
```

## Build Result

- Documents processed: 20
- Raw candidates: 756
- Merged/linked candidates: 551
- Validation: PASS
- Output: `outputs/new_arch_silver_eval/output`
- Report: `reports/silver_eval_new_arch_scoped.md`

## Silver Score

| Metric | Score |
|---|---:|
| text_score | 0.262711 |
| assertions_score | 0.083333 |
| candidates_score | 0.038855 |
| final_score | 0.119355 |

## Diagnostic Exact-Match Metrics

| Metric | Precision | Recall | F1 |
|---|---:|---:|---:|
| span_type | 0.1706 | 0.2541 | 0.2041 |
| full_entity | 0.0998 | 0.1486 | 0.1194 |
| assertions_on_matched_spans | 0.1333 | 0.3636 | 0.1951 |
| candidates_on_matched_spans | 0.1875 | 0.1429 | 0.1622 |

## Per-Type F1

| Type | F1 |
|---|---:|
| THUỐC | 0.3333 |
| CHẨN_ĐOÁN | 0.2577 |
| TRIỆU_CHỨNG | 0.2511 |
| KẾT_QUẢ_XÉT_NGHIỆM | 0.0789 |
| TÊN_XÉT_NGHIỆM | 0.0132 |

## Takeaway

The active architecture validates cleanly on the scoped silver run, but silver alignment remains low. The largest gap is candidate/linking quality and over-generation, especially for lab-name extraction (`TÊN_XÉT_NGHIỆM`) and symptom spans.

## Architecture Coverage

This checkpoint exercised the active new-architecture output builder implemented in `scripts/build_new_arch_outputs.py`. The evaluated pipeline was:

```text
input loading
→ offset-preserving section parsing
→ optional NER seed collection
→ specialized lab parser
→ specialized drug parser
→ diagnosis/symptom/structural dictionary-rule extraction
→ non-target rejection
→ assertion tagging
→ merge/deduplication
→ ICD-10/RxNorm candidate linking
→ output writing
→ schema/offset/overlap validation
→ silver scoring
```

Because the command did not pass `--ner-model`, this run covered the **NER-optional parser/rule architecture without neural NER inference**:

```text
parser_architecture = ner_optional_drug_parser_lab_parser_dictionary_rules
ner_candidates = 0
```

So the run covered the architecture hooks for NER seed ingestion, but did **not** evaluate ViHealthBERT/Hugging Face token-classification quality.

### Covered Components

| Layer | Main implementation | Coverage in this run |
|---|---|---|
| Input/section parsing | `src/io_utils.py`, `src/section_parser.py`, `src/models.py` | Loaded and parsed 20 selected input documents with raw character offsets preserved. |
| Lab parser | `src/lab_parser.py` | Extracted lab names/results using curated dictionaries, local structure, result detection, and name-result pairing. |
| Drug parser | `src/drug_parser.py` | Extracted medication spans from dictionary seeds, boundary composition, dose parsing, and RxNorm prelink evidence. |
| Diagnosis rules | `src/rule_extractors.py` | Extracted diagnosis spans through dictionary/context rules and structural fallback. |
| Symptom rules | `src/rule_extractors.py` | Extracted symptom spans through symptom dictionaries, section rules, and structural fallback. |
| Non-target rejection | `src/rule_extractors.py` | Rejected 99 procedure/imaging-like non-target spans before final output. |
| Assertions | `src/assertion.py` | Added negation/historical assertions before merge/linking. |
| Merge/deduplication | `src/merge.py` | Reduced 756 raw candidates to 551 merged/linked final entities. |
| Candidate linking | `src/linking/candidate_linker.py`, `src/linking/icd10_linker.py`, `src/linking/rxnorm_linker.py` | Linked mappable diagnosis/drug spans to ICD-10/RxNorm candidates. |
| Output/validation | `src/output_writer.py`, `src/validator.py` | Wrote JSON output/zip artifacts and passed schema, offset, duplicate, overlap, and zip validation. |
| Silver scoring | `scripts/score_silver.py` | Compared generated output against `silver_test/output` for the 20 scoped files. |

### Empirical Extraction Coverage

Raw extraction summary from `analysis/new_arch_silver_eval/span_candidates_new_arch_summary.json`:

| Type | Raw candidates |
|---|---:|
| `TRIỆU_CHỨNG` | 363 |
| `TÊN_XÉT_NGHIỆM` | 134 |
| `CHẨN_ĐOÁN` | 104 |
| `THUỐC` | 29 |
| `KẾT_QUẢ_XÉT_NGHIỆM` | 27 |

Final validated output after assertion, merge, and linking:

| Type | Final entities |
|---|---:|
| `TRIỆU_CHỨNG` | 297 |
| `TÊN_XÉT_NGHIỆM` | 111 |
| `CHẨN_ĐOÁN` | 87 |
| `THUỐC` | 29 |
| `KẾT_QUẢ_XÉT_NGHIỆM` | 27 |

Key source tags observed in the run:

| Source tag | Raw count | Linked/final count |
|---|---:|---:|
| `structural_fallback` | 341 | 248 |
| `section_rule` | 200 | 189 |
| `symptom_dictionary` | 161 | 151 |
| `lab_parser` | 90 | 88 |
| `lab_dictionary` | 63 | 61 |
| `diagnosis_dictionary` | 39 | 38 |
| `result_detection` | 27 | 27 |
| `paired_with_dictionary_name` | 27 | 27 |
| `drug_parser` | 26 | 26 |
| `drug_dictionary` | 26 | 26 |
| `boundary_composition` | 26 | 26 |
| `dose_parser` | 3 | 3 |

The high `structural_fallback`, `section_rule`, and `symptom_dictionary` counts explain much of the over-generation noted by the silver diagnostics.

### Mapping Coverage

Only `CHẨN_ĐOÁN` and `THUỐC` are candidate-mappable concept types. The run produced 116 mappable final spans:

| Type | Mapped | Total | Coverage |
|---|---:|---:|---:|
| `THUỐC` | 18 | 29 | 62.1% |
| `CHẨN_ĐOÁN` | 38 | 87 | 43.7% |
| Combined | 56 | 116 | 48.3% |

Mapping source counts:

| Mapping source | Count |
|---|---:|
| `icd_exact` | 38 |
| `icd_unmapped` | 49 |
| `rxnorm_exact` | 17 |
| `rxnorm_alias_or_ingredient` | 1 |
| `rxnorm_unmapped` | 11 |

This incomplete mapping coverage is consistent with the low silver `candidates_score` of `0.038855`.

### Validation Coverage

The run validates the final architecture artifacts structurally:

| Validation check | Result |
|---|---:|
| Total entities | 551 |
| Schema errors | 0 |
| Offset errors | 0 |
| Duplicate errors | 0 |
| Overlap errors | 0 |
| Zip errors | 0 |
| Empty files | 0 |

Assertions present in final output:

| Assertion | Count |
|---|---:|
| `isHistorical` | 75 |
| `isNegated` | 53 |

### Not Covered By This Checkpoint

- Neural NER inference quality, because no `--ner-model` was supplied.
- Full-dataset behavior, because the run was scoped to 20 files.
- Training/fine-tuning workflows; this was an inference and scoring checkpoint only.
- Direct old-vs-new architecture comparison; this report evaluates only the active new architecture against silver labels.
- Official hidden-test performance; the gold side is the local `silver_test/output` approximation.

### Architecture Coverage Conclusion

The checkpoint confirms that the deterministic active architecture is end-to-end executable and output-valid on the 20-file silver scope. It covers parser/rule extraction, assertion tagging, merge/deduplication, candidate linking, output writing, validation, and silver scoring. The main remaining quality gaps are semantic alignment, over-generation from structural/symptom rules, poor lab-name precision/recall, and incomplete ICD/RxNorm mapping coverage.