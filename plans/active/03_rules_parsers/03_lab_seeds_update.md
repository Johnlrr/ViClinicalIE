# Plan: Combined PDF Lab Catalog + Abbreviation Alias Upgrade for `lab_parser`

## 1. Objective

Improve the lab parser by replacing the current small flat `lab_seed_terms.csv` with a curated, evidence-aware lab dictionary built in **three ordered stages**:

1. **Combine the two PDF catalogs into one unified lab catalog source**:
   - [`data_resources/lab_list.pdf`](../../data_resources/lab_list.pdf) — hospital laboratory catalog, useful for common Vietnamese lab names and local naming variants.
   - [`data_resources/lab_med_ministry.pdf`](../../data_resources/lab_med_ministry.pdf) — Bộ Y tế official biochemical procedure list, useful for canonical Vietnamese names, official procedure names, specimen/context groups, and English abbreviation aliases.
2. **Extract lab-name aliases from the two PDFs first**, including concise catalog names, parenthetical abbreviations, and normalized variants from the combined PDF catalog.
3. **Check [`data_resources/abbreviation.txt`](../../data_resources/abbreviation.txt) only as an additional alias source for lab names**, adding aliases that are missing from the PDF-derived aliases and linking them back to canonical lab tests whenever possible. Then feed the final combined-and-aliased resource into `lab_parser` so dictionary matching can use canonical IDs, aliases, provenance, and ambiguity/context flags.

This plan assumes the system is being rebuilt, so legacy build scripts are not treated as constraints. The goal is to design the next `lab_parser` resource layer and extraction behavior, not just append many rows blindly to the old CSV.

### 1.1 Required source precedence and data flow

```text
lab_list.pdf ─────────────┐
                          ├─> combined_lab_catalog.csv ──┐
lab_med_ministry.pdf ─────┘                               │
                                                          ├─> lab_terms_curated.csv / lab_canonical_map.csv ──> lab_parser
PDF-derived aliases ────────────────┤
abbreviation.txt ──> additional aliases ─────┘
```

Interpretation:

- The **combined PDF catalog** is the primary inventory of lab tests and canonical lab concepts.
- Alias extraction order is: **PDF-derived aliases first**, then `abbreviation.txt` as a supplemental check for additional aliases not already recovered from the PDFs.
- If an abbreviation is lab-relevant but cannot be linked to a PDF-derived lab name/canonical entry, it should be flagged for curation before becoming a new canonical lab concept.
- `lab_parser` should consume the final curated resource, not raw PDF text and not raw abbreviation lines.

---

## 2. Current lab seed state and limitation

Current file: [`data_resources/lab_seed_terms.csv`](../../data_resources/lab_seed_terms.csv)

Current terms:

```text
WBC, RBC, HGB, HCT, PLT, NEUT%, LYMPH%, LYPH%, glucose, creatinine, BUN,
AST, ALT, bilirubin, troponin, INR, CRP, lactate, UA, CBC, công thức máu,
xét nghiệm chức năng gan, bạch cầu, kali, cea, huyết khối, k
```

Main limitations:

- Coverage is very small: it covers a few CBC, chemistry, cardiac, liver, and coagulation terms, but misses many common terms already visible in the input notes such as `cr`, `ure`, `canxi`, `calci`, `phospho`, `photpho`, `alp`, `lipase`, `hba1c`, `ck`, `ferritin`.
- The current resource is flat: no canonical ID, no alias provenance, no ambiguity flag, no specimen type, no section/category, no full-name/abbreviation pair.
- Short ambiguous tokens such as `k` are dangerous if matched globally without context. They should be kept, but only under stronger context/result-pairing constraints.
- Parenthetical aliases are detected in the parser (`cea (kháng nguyên ung thư phôi)`), but the dictionary does not store abbreviation-to-expansion mappings explicitly.

---

## 3. Resource analysis

### 3.1 Source role summary

The resources have different roles in the target workflow:

| Source | Role | Output contribution |
|---|---|---|
| `lab_med_ministry.pdf` | Official/canonical biochemical procedure inventory | Canonical names, official names, specimen groups, official parenthetical abbreviations |
| `lab_list.pdf` | Practical hospital catalog | Local/common aliases, concise note-like terms, additional lab domains such as hematology/coagulation/serology |
| `abbreviation.txt` | Supplemental alias source only | Additional abbreviation-to-expansion aliases checked after PDF-derived aliases and attached to canonical lab names where possible |

The two PDFs should be extracted, normalized, deduplicated, and used to generate initial aliases **before** `abbreviation.txt` is checked for additional aliases.

### 3.2 `abbreviation.txt`

Format observed:

```text
ABBR Vietnamese/English explanation
```

Examples:

```text
ALT alanine aminotransferase (tên gọi trước đây là SGPT)
AST aspartate aminotransferase (tên gọi trước đây là SGOT)
BUN urea nitrogen trong máu
CBC công thức máu
CK-MB isoenzyme creatine kinase dải cơ
ESR tốc độ máu lắng
Hb hemoglobin
Hct hematocrit
INR tỉ lệ chuẩn hóa quốc tế
K kali
Na natri
RBC hồng cầu
WBC bạch cầu
```

#### Lab-relevant abbreviation candidates

High-value candidates from `abbreviation.txt`:

| Abbreviation | Expansion/gloss | Proposed use |
|---|---|---|
| `ABG` | khí máu động mạch | Add as alias for blood gas / arterial blood gas |
| `ACTH` | hoóc môn hướng vỏ thượng thận | Add; also confirmed in PDFs |
| `ALT` | alanine aminotransferase / SGPT | Already present; add `SGPT` alias |
| `AST` | aspartate aminotransferase / SGOT | Already present; add `SGOT` alias |
| `BUN` | urea nitrogen trong máu | Already present; map to urea/ure group |
| `Ca` | can xi | Add only as context-gated alias; also add safer full forms `canxi`, `calci` |
| `CBC` | công thức máu | Already present |
| `CK` | creatine kinase | Add |
| `CK-MB` | isoenzyme creatine kinase dải cơ | Add |
| `Cl` | clo | Context-gated electrolyte alias |
| `CO2` | khí cácbônic | Context-gated blood gas/electrolyte alias |
| `ESR` | tốc độ máu lắng | Add |
| `G6PD` | glucose-6-phosphate dehydrogenase | Add |
| `Hb` | hemoglobin | Add; normalize with existing `HGB` |
| `HCO3` | bicarbonate | Add |
| `Hct` | hematocrit | Already covered by `HCT`, keep case variants |
| `INR` | tỉ lệ chuẩn hóa quốc tế | Already present |
| `K` | kali | Already present as `k`; mark high ambiguity/context-gated |
| `LDH` | lactic dehydrogenase | Add |
| `MCH` | lượng huyết sắc tố trung bình trong một hồng cầu | Add |
| `MCHC` | nồng độ huyết sắc tố trung bình trong một hồng cầu | Add |
| `MCV` | thể tích trung bình hồng cầu | Add |
| `Mg` | magiê | Add with context gate; also add full form `magie/magiê` |
| `Na` | natri | Add with context gate; also add full form `natri` |
| `pH` | hydrogen ion concentration | Add, primarily in ABG/urinalysis context |
| `PMN` | bạch cầu đa nhân | Add if CBC/differential context is supported |
| `PT` | thời gian prothrombin | Add, but protect from English word collision by case/boundary/context |
| `PTT` | thời gian thromboplastin riêng phần | Add |
| `RBC` | hồng cầu | Already present |
| `SaO2` | độ bão hòa ô-xi động mạch | Add blood gas alias |
| `WBC` | bạch cầu | Already present |

#### Abbreviations to exclude from lab seeds

Do not add these to lab seed terms, even if medically meaningful, because they represent diagnoses, procedures, departments, measurements, medications, or non-lab concepts:

```text
ACE, AIDS, BCG, bid, BP, CNS, COPD, CPR, CT, D&C, DNA, DTP, ECG, EEG,
ENT, ERCP, FDA, GI, GU, ICU, IM, IV, IVU, MRI, NSAID, OTC, PET, po, prn,
RA, RNA, SLE, SSRI, TB, TPN, URI, UTI, WHO
```

Also do not add pure units as lab-name seeds:

```text
cm, dL, g, h, IU, kg, L, m, mEq, mg, mIU, mL, mm, mmol, ng, nm, nmol,
pg, ppm, μg, μL, μm, μmol
```

#### Special handling for single-letter / very short abbreviations

The following are lab-relevant but ambiguous and should not be globally matched as ordinary dictionary terms:

```text
C, Ca, Cl, K, Mg, Na, N, O2, P, pH
```

Recommended parser policy:

- Match them only if at least one of these holds:
  - line is in/near lab section;
  - line contains lab-result marker (`xét nghiệm`, `cận lâm sàng`, `kết quả xét nghiệm`, `chem`, `điện giải`, `khí máu`);
  - a result pattern follows immediately (`K 5.4`, `Na: 138`, `Ca là 12.0`, `pH 7.32`);
  - term appears in parenthetical expansion after a safer full name (`k (kali)`).
- Store `requires_context=true` in the dictionary metadata.

---

## 4. PDF extraction analysis

### 4.1 `lab_med_ministry.pdf`

Important pages: pages 2-7 contain the official list of 220 biochemical procedures. These pages are more valuable than the long technical SOP sections that follow.

Extracted structure examples:

```text
A. MÁU
1 Đo hoạt độ ACP (Phosphatase Acid)
2 Định lượng ACTH
3 Định lượng Acid Uric
7 Định lượng Albumin
9 Đo hoạt độ ALP (Alkalin Phosphatase)
19 Đo hoạt độ ALT (GPT)
20 Đo hoạt độ AST (GOT)
24 Định lượng βhCG (Beta human Chorionic gonadotropins)
29 Định lượng Calci toàn phần
30 Định lượng Calci ion hoá
39 Định lượng CEA (carcino embryonic antigen)
41 Định lượng Cholesterol toàn phần
42 Đo hoạt độ CK (Creatine kinase)
43 Đo hoạt độ CK-MB (Isozym MB of Creatine kinase)
50 Định lượng CRP hs (C-reactive protein high sensitivity)
51 Định lượng Creatinin
54 Định lượng D-Dimer
58 Định lượng các chất điện giải (Na, K, Cl)
63 Định lượng Ferritin
75 Định lượng Glucose
83 Định lượng HbA1c
84 Định lượng HDL-C
103 Xét nghiệm Khí máu
104 Định lượng Lactat
109 Đo hoạt độ Lipase
111 Đo hoạt độ LDH
112 Định lượng LDL-C
121 Định lượng NT-proBNP
128 Định lượng Phospho
133 Định lượng Protein toàn phần
143 Định lượng Sắt
158 Định lượng Triglycerid
159 Định lượng Troponin T
160 Định lượng Troponin T hs
161 Định lượng Troponin I
162 Định lượng TSH
166 Định lượng Urê

B. NƯỚC TIỂU
172 Định lượng các chất điện giải
175 Đo hoạt độ Amylase
176 Định lượng axit uric
180 Định lượng Canxi
184 Định lượng Creatinin
194 Định lượng Phospho
202 Định lượng Ure
203 Tổng phân tích nước tiểu

C. DỊCH NÃO TUỶ
204 Định lượng Clo
205 Định lượng Glucose
206 Phản ứng Pandy
207 Định lượng Protein

E. DỊCH CHỌC DÒ
210 Đo hoạt độ Amylase
211 Định lượng Bilirubin toàn phần
212 Định lượng Cholesterol toàn phần
213 Định lượng Creatinin
214 Định lượng Glucose
215 Đo hoạt độ LDH
216 Định lượng Protein toàn phần
218 Định lượng Triglycerid
220 Định lượng Ure
```

Recommended use:

- Use the numbered list as canonical lab test inventory.
- Strip procedure prefixes (`Định lượng`, `Định tính`, `Đo hoạt độ`, `Điện di`, `Xét nghiệm`, `Tổng phân tích`) to derive match aliases.
- Preserve the original official name as `canonical_name` / `official_name`.
- Preserve category/specimen (`MÁU`, `NƯỚC TIỂU`, `DỊCH NÃO TUỶ`, `DỊCH CHỌC DÒ`) as metadata.
- Extract abbreviation aliases from parentheses, e.g. `ALP`, `CK`, `CK-MB`, `CEA`, `CRP hs`, `D-Dimer`, `HbA1c`, `LDL-C`, `HDL-C`, `NT-proBNP`, `TSH`.

### 4.2 `lab_list.pdf`

This hospital catalog is useful as a practical/local alias source. It contains common short names and Vietnamese clinical surface forms, often closer to notes than official procedure names.

High-value terms extracted from the lab catalog include:

```text
Ure máu, Creatinin máu, Glucose máu, HbA1C, Proteid máu, Albumin máu,
Globulin, Cholesterol, HDL, LDL, Triglycerid, Acid uric máu,
Bilirubin toàn phần, Bilirubin trực tiếp, AST, ALT, GGT, ALP, LDH,
α-amylase máu, Lipase máu, CPK, CK-MB, CRP, CRPhs, D-Dimer, RF, ASLO,
Sắt, Phospho, calci, calci ion hóa, Khí máu động mạch, T3, T4, FT3, FT4,
TSH, AFP, CEA, CA 19-9, CA 72-4, CA 15-3, CA 125, PSA toàn phần, PSA tự do,
Cyfra 21-1, NSE, HE4, SCC, Anti-CCP, Feritin, Troponin I, Troponin T hs,
PCT, Pro BNP, ProGRP, ACTH, Cortisol, β-HCG, LH, FSH, Estradiol,
Progesterol, Testosterol, PTH, HBsAg, Anti-HBsAg, Anti-HCV,
TPT nước tiểu, Microalbumin niệu, Protein niệu, Phản ứng rivalta,
Phản ứng pandy, α-amylase niệu, Acid uric niệu, Ure niệu, Creatinin niệu,
Protein dịch chọc dò, Đường dịch não tủy, Clo dịch não tủy, Điện giải niệu,
Máu lắng, Huyết đồ, APTT, PT, TT, Fibrinogen, HIV Ag/Ab, HCV Ab, ANA,
Anti dsDNA, Coombs trực tiếp, Coombs gián tiếp
```

Recommended use:

- Treat it as alias enrichment, not as the single source of truth.
- Prefer its concise terms for actual matching (`Ure máu`, `calci ion hóa`, `Troponin I`, `TPT nước tiểu`).
- Keep section/category metadata (`Hóa sinh`, `Vi sinh`, `Huyết học-Đông máu`, etc.) where possible, but do not rely on PDF page headers alone as authoritative because extraction is noisy.

---

## 5. Proposed resource design for rebuilt system

Instead of only maintaining a flat CSV, create one intermediate combined PDF catalog and two final parser-facing resources:

### 5.1 `combined_lab_catalog.csv` — merged catalog from the two PDFs

This is the output of step 1 and should contain one row per extracted PDF lab/procedure entry before abbreviation alias enrichment.

Suggested columns:

```csv
source_pdf,source_page,source_item,raw_name,normalized_name,canonical_key,canonical_name,category,specimen,official_name,local_name,notes
```

Column meanings:

| Column | Meaning |
|---|---|
| `source_pdf` | `lab_med_ministry_pdf` or `lab_list_pdf` |
| `source_page` | PDF page used for traceability |
| `source_item` | Numbered item/code where available |
| `raw_name` | Exact extracted PDF row/name |
| `normalized_name` | Procedure prefixes stripped and typography normalized |
| `canonical_key` | Stable grouping key used after deduplication |
| `canonical_name` | Human-readable canonical test name |
| `category` | chemistry, hematology, coagulation, immunology, microbiology, urinalysis, blood_gas, tumor_marker |
| `specimen` | blood, urine, csf, puncture_fluid, stool, unknown |
| `official_name` | Official ministry name when available |
| `local_name` | Local hospital catalog name when available |
| `notes` | Extraction ambiguity, merge notes, or curation comments |

Merge policy:

- Prefer `lab_med_ministry.pdf` for official biochemical canonical naming.
- Preserve `lab_list.pdf` names as practical aliases/local names, especially when they are closer to clinical notes.
- Deduplicate by normalized Vietnamese/English names, parenthetical abbreviations, and known equivalence rules (`Creatinin`/`Creatinine`, `Ure`/`Urê`, `Calci`/`Canxi`).
- Keep provenance from both PDFs when entries merge into the same `canonical_key`.

### 5.2 `lab_terms.csv` — alias-level matching dictionary

Suggested columns:

```csv
term,canonical_key,canonical_name,source,source_detail,category,specimen,requires_context,priority,notes
```

Column meanings:

| Column | Meaning |
|---|---|
| `term` | Surface form to match in clinical text |
| `canonical_key` | Stable normalized key, e.g. `creatinine`, `potassium`, `ck_mb`, `blood_gas` |
| `canonical_name` | Human-readable canonical test name |
| `source` | `combined_lab_catalog`, `abbreviation_txt_alias`, `current_seed`, `manual_curation` |
| `source_detail` | Combined catalog row ID, PDF page/list number, or abbreviation line |
| `category` | chemistry, hematology, coagulation, immunology, microbiology, urinalysis, blood_gas, tumor_marker |
| `specimen` | blood, urine, csf, puncture_fluid, stool, unknown |
| `requires_context` | true for short/ambiguous aliases (`K`, `Na`, `Ca`, `PT`, `Cl`, `pH`) |
| `priority` | matching priority; current/manual curated > abbreviation/PDF-derived |
| `notes` | ambiguity or mapping notes |

### 5.3 `lab_canonical_map.csv` — canonical test grouping

Suggested columns:

```csv
canonical_key,canonical_name,category,default_specimen,aliases,external_source_notes
```

Examples:

```csv
creatinine,Creatinin,chemistry,blood,"creatinine|creatinin|creatinin máu|cr",lab_med_ministry item 51; lab_list item 2
urea,Ure/BUN,chemistry,blood,"ure|urê|ure máu|urea|bun|urea nitrogen trong máu",lab_med_ministry item 166; abbreviation BUN
potassium,Kali,chemistry,blood,"kali|k",abbreviation K; current seed
calcium,Calci/Canxi,chemistry,blood,"calci|canxi|calci toàn phần|canxi toàn phần|calci ion hóa|canxi ion hóa|ca",lab_med_ministry item 29-31; abbreviation Ca
glucose,Glucose,chemistry,blood,"glucose|glucose máu|đường huyết",lab_med_ministry item 75; lab_list item 3
ck_mb,CK-MB,cardiac,blood,"ck-mb|ck mb|ck-mb mass",lab_med_ministry item 43-44; abbreviation CK-MB
```

The parser can still accept a simple `Sequence[str]` for compatibility, but the rebuilt system should load the richer CSV and expose both:

- `lab_alias_terms`: list of matchable terms;
- `lab_catalog`: map from alias to canonical metadata.

The final parser-facing resources should be derived from `combined_lab_catalog.csv` plus abbreviation alias mapping. Raw PDF rows and raw abbreviation lines should not be consumed directly by `lab_parser`.

---

## 6. Plan of execution

This section converts the methodology above into an execution sequence. The goal is not to apply lab terms by tiers, but to build one traceable resource pipeline where aliases are generated in the correct order and then curated before parser integration.

### 6.1 Build the combined PDF catalog

Inputs:

```text
data_resources/lab_med_ministry.pdf
data_resources/lab_list.pdf
```

Execution steps:

1. Extract structured text/tables from both PDFs.
2. Parse `lab_med_ministry.pdf` as the preferred official source for canonical biochemical names, official procedure names, specimen groups, and official parenthetical aliases.
3. Parse `lab_list.pdf` as the local/practical catalog source for concise Vietnamese lab names, common hospital naming variants, and broader lab domains such as hematology, coagulation, urinalysis, serology, and microbiology.
4. Normalize extracted names:
   - strip procedure prefixes such as `Định lượng`, `Định tính`, `Đo hoạt độ`, `Xét nghiệm`, `Tổng phân tích`;
   - normalize case, whitespace, hyphens, Greek letters, accents, and common spelling variants;
   - preserve the exact raw extracted text for traceability.
5. Merge the two PDF sources into `combined_lab_catalog.csv` using stable `canonical_key` values.
6. Preserve source provenance so each canonical lab concept can trace back to one or both PDFs.

Expected output:

```text
data_resources/generated/combined_lab_catalog.csv
```

### 6.2 Extract aliases from the combined PDF catalog first

Alias extraction should happen from the PDF-derived combined catalog before `abbreviation.txt` is consulted.

Alias sources inside the PDFs:

1. Local concise names from `lab_list.pdf`, for example:

   ```text
   Ure máu
   Creatinin máu
   calci ion hóa
   Khí máu động mạch
   TPT nước tiểu
   Troponin I
   ```

2. Prefix-stripped official names from `lab_med_ministry.pdf`, for example:

   ```text
   Định lượng Creatinin -> Creatinin
   Đo hoạt độ CK-MB -> CK-MB
   Xét nghiệm Khí máu -> Khí máu
   Tổng phân tích nước tiểu -> Tổng phân tích nước tiểu
   ```

3. Parenthetical aliases already present in PDF rows, for example:

   ```text
   Đo hoạt độ AST (GOT) -> AST, GOT
   Đo hoạt độ ALT (GPT) -> ALT, GPT
   Định lượng CEA (carcino embryonic antigen) -> CEA, carcino embryonic antigen
   Định lượng CRP hs (C-reactive protein high sensitivity) -> CRP hs, CRPhs
   ```

4. Normalized spelling and orthographic variants derived from PDF terms, for example:

   ```text
   urê <-> ure
   canxi <-> calci
   creatinin <-> creatinine
   ferritin <-> feritin
   phospho <-> photpho
   β-HCG <-> beta HCG <-> hcg
   α-amylase <-> alpha amylase <-> amylase
   CRP hs <-> CRPhs
   D-Dimer <-> D dimer <-> ddimer
   NT-proBNP <-> NT pro BNP <-> pro BNP
   ```

Expected outputs:

```text
data_resources/generated/pdf_alias_links.csv
data_resources/generated/lab_terms_candidates.csv
```

### 6.3 Check `abbreviation.txt` for additional lab-name aliases

After PDF-derived aliases are created, use `abbreviation.txt` as a supplemental source only.

Execution steps:

1. Read `abbreviation.txt` line by line and split each row into abbreviation and explanation/gloss.
2. Apply lab/non-lab filtering before accepting an abbreviation.
3. Compare accepted abbreviation candidates against aliases already extracted from the combined PDF catalog.
4. Add an abbreviation only if it contributes a missing alias for an existing or curated lab name.
5. Link each accepted abbreviation to a `canonical_key` from `combined_lab_catalog.csv` whenever possible.
6. If an abbreviation looks lab-relevant but cannot be linked to a PDF-derived canonical lab name, send it to curation instead of adding it automatically.
7. Mark short or ambiguous aliases with `requires_context=true`, for example:

   ```text
   K, Ca, Cl, Mg, Na, PT, pH, cr, ck, Hb, Hct
   ```

Expected output:

```text
data_resources/generated/abbreviation_alias_links.csv
```

### 6.4 Curate accepted, rejected, and context-required aliases

The generated candidates should be reviewed before becoming parser-facing resources.

Curation decisions:

```text
accept
accept_context_required
reject_non_lab
reject_unit
reject_ambiguous
defer_guideline_check
```

Important curation rules:

- Do not add units as lab-name aliases.
- Do not add generic words such as `máu`, `dịch`, `test`, or `định lượng` as standalone aliases.
- Do not add non-lab abbreviations from `abbreviation.txt` even if medically meaningful.
- Keep short aliases only when they are attached to a canonical lab concept and protected by context gates.
- Preserve `source`, `source_detail`, and `notes` for every accepted alias.

Expected final resources:

```text
data_resources/lab_terms_curated.csv
data_resources/lab_canonical_map.csv
```

### 6.5 Feed curated resources into `lab_parser`

The parser should load the final curated resources, not raw PDFs and not raw `abbreviation.txt` rows.

Parser-facing resource behavior:

1. `lab_terms_curated.csv` provides alias-level matching entries.
2. `lab_canonical_map.csv` provides canonical grouping for matched aliases.
3. The parser should be able to expose:

   ```python
   lab_alias_terms: Sequence[str]
   lab_catalog: Mapping[str, LabTermEntry]
   ```

4. For backward compatibility, the parser may still accept a simple `Sequence[str]`, but the preferred path should use metadata-backed entries.

### 6.6 Validate the resource pipeline

Validation should cover both resource generation and parser behavior:

1. PDF extraction samples from both PDFs.
2. Combined catalog deduplication.
3. PDF-derived alias generation.
4. Supplemental alias linking from `abbreviation.txt`.
5. Rejection of non-lab abbreviations and pure units.
6. Context-required behavior for ambiguous aliases.
7. Offset round-trip checks in parser output.
8. Regression tests on real clinical examples already observed in notes.

---

## 7. Improvements needed in `lab_parser.py` for the new lab dictionary

The new dictionary is no longer a flat list of strings. `lab_parser.py` should be updated so it can use alias metadata, canonical lab identity, source provenance, and ambiguity controls while preserving the current span extraction behavior.

### 7.1 Load metadata-backed lab terms

Add a parser resource model for curated dictionary rows:

```python
@dataclass(frozen=True)
class LabTermEntry:
    term: str
    canonical_key: str
    canonical_name: str
    source: str
    source_detail: str
    category: str
    specimen: str
    requires_context: bool
    priority: int
    notes: str = ""
```

Recommended loader behavior:

1. Read `lab_terms_curated.csv` into `LabTermEntry` objects.
2. Build an alias lookup keyed by normalized term.
3. Preserve compatibility with the current `Sequence[str]` input by converting bare strings into minimal `LabTermEntry` objects when needed.
4. Keep duplicate aliases only if they resolve to the same canonical concept or are explicitly disambiguated by category/specimen/context.

### 7.2 Add canonical metadata to parser trace

Current `LabParseTrace` records dictionary evidence but should also record canonical lab identity.

Add fields such as:

```python
canonical_key: Optional[str]
canonical_name: Optional[str]
source_detail: Optional[str]
category: Optional[str]
specimen: Optional[str]
requires_context: bool
```

Purpose:

- keep output spans unchanged;
- make debugging easier;
- allow downstream systems to normalize aliases such as `cr`, `creatinin`, and `creatinine` to one canonical lab identity;
- preserve traceability back to PDF-derived aliases or supplemental abbreviation aliases.

### 7.3 Apply context gates for ambiguous aliases

Use `requires_context` from `LabTermEntry`. A context-required alias should be accepted only when at least one strong lab signal is present.

Accept when one of these conditions holds:

- the line is in or near a lab/cận-lâm-sàng section;
- the line contains lab markers such as `xét nghiệm`, `cận lâm sàng`, `kết quả`, `điện giải`, `khí máu`, `chem`, `cbc`, `đông máu`, or `huyết học`;
- a result pattern follows immediately, such as `K 5.4`, `Na: 138`, `Ca là 12.0`, `pH 7.32`;
- the alias appears in a parenthetical alias/expansion pattern, such as `cr (creatinine)` or `k (kali)`.

Context-required examples:

```text
K, k, Ca, Cl, Mg, Na, PT, pH, cr, ck, Hb, Hct
```

### 7.4 Resolve overlapping alias matches before result pairing

The expanded dictionary will create more overlapping matches. Resolve overlaps before result pairing.

Examples:

```text
bilirubin vs bilirubin toàn phần
canxi vs canxi ion hóa
CRP vs CRP hs
Troponin T vs Troponin T hs
```

Suggested ordering:

1. Higher `priority` wins.
2. Longer/more specific span wins.
3. Non-context-required alias wins over context-required alias when both are otherwise equivalent.
4. Manual/current curated source wins over generated alias.
5. If still tied, prefer the alias with richer canonical metadata.

### 7.5 Preserve parenthetical alias expansion behavior

The current parser already expands lab-name spans around parenthetical aliases, for example:

```text
cea (kháng nguyên ung thư phôi)
cr (creatinine)
```

Keep this behavior, but connect it to dictionary metadata:

- if the abbreviation and expansion map to the same `canonical_key`, treat the full parenthetical expression as strong evidence;
- if only one side is known, use the known side to infer the candidate canonical key but lower confidence or mark for trace review;
- if both sides map to different canonical keys, avoid automatic merging and keep trace evidence for debugging.

### 7.6 Expand result and unit recognition without turning units into lab aliases

The new PDF-derived dictionary contains tests that commonly use additional units. `lab_parser.py` should recognize these units in result spans, but the resource builder must still reject them as lab-name aliases.

Additional unit/result forms to support:

```text
IU/L, mIU/L, µIU/mL, ng/L, pmol/L, nmol/L, µmol/L, fL, pg, %, mm/h, COI
```

Important distinction:

- units may appear in `KẾT_QUẢ_XÉT_NGHIỆM` spans;
- units must not be accepted as `TÊN_XÉT_NGHIỆM` aliases.

### 7.7 Keep output compatibility while adding normalization

The parser should continue returning the existing `SpanCandidate` labels:

```text
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
```

The new canonical metadata should be added in `SpanCandidate.notes` / parser trace rather than changing the public span labels immediately.

Recommended compatibility behavior:

1. Preserve current offsets and text spans.
2. Preserve current labels and score semantics as much as possible.
3. Add canonical metadata as optional trace fields.
4. Ensure `doc.raw_text[start:end] == candidate.text` remains true for every emitted candidate.

### 7.8 Add tests for the new dictionary behavior

Add or update tests for:

1. Loading `lab_terms_curated.csv` into `LabTermEntry` objects.
2. Matching aliases to canonical keys.
3. Context-gated aliases:
   - `k 5.4` in lab context -> accepted;
   - `k` in ordinary prose -> rejected;
   - `cr (creatinine) 1.2` -> accepted;
   - `pt` without coagulation/lab/result context -> rejected.
4. Overlap resolution:
   - prefer `bilirubin toàn phần` over `bilirubin`;
   - prefer `canxi ion hóa` over `canxi`;
   - prefer `CRP hs` over `CRP`.
5. Unit recognition for result spans.
6. Offset round-trip checks.
7. Regression examples:
   - `canxi là 12.0; canxi ion hóa 6.8`;
   - `cr (creatinine) 1.2`;
   - `Ure tăng từ 69 lên 91 mg/dl ... photpho 8.4`;
   - `alp 185`;
   - `ferritin là bình thường`;
   - `ck 58`.

---

## 8. Proposed implementation workflow

### Step 1 — combine the two PDF files into one lab catalog

Create a one-off resource-building script for the rebuilt system, e.g.:

```text
scripts/resources/build_lab_terms.py
```

Responsibilities for the PDF-combine stage:

1. Use `pdfplumber` to extract pages 2-7 from `lab_med_ministry.pdf` and all relevant numbered rows from `lab_list.pdf`.
2. Parse official names, local names, categories, specimen groups, item numbers, and parenthetical aliases found inside the PDFs.
3. Normalize names by stripping procedure prefixes (`Định lượng`, `Định tính`, `Đo hoạt độ`, `Xét nghiệm`, etc.) and normalizing typography/case.
4. Merge/deduplicate the two PDF sources into one combined catalog keyed by `canonical_key`.
5. Preserve provenance from both source PDFs for traceability.

Output of this stage:

```text
data_resources/generated/combined_lab_catalog.csv
```

### Step 2 — extract aliases from the combined PDF catalog

Responsibilities for the PDF alias stage:

1. Generate aliases from the combined PDF catalog before consulting `abbreviation.txt`.
2. Keep concise names from `lab_list.pdf` as practical aliases, e.g. `Ure máu`, `calci ion hóa`, `Troponin I`, `TPT nước tiểu`.
3. Generate aliases from `lab_med_ministry.pdf` by removing procedure prefixes, e.g. `Định lượng Creatinin` -> `Creatinin`, `Xét nghiệm Khí máu` -> `Khí máu`.
4. Extract parenthetical aliases already present in PDF rows, e.g. `ALT (GPT)` -> `ALT`, `GPT`; `CK-MB (Isozym MB of Creatine kinase)` -> `CK-MB`.
5. Normalize orthographic variants from PDF-derived terms, e.g. `Ure`/`Urê`, `Calci`/`Canxi`, `Creatinin`/`Creatinine`.
6. Mark short/ambiguous PDF-derived aliases (`K`, `Na`, `Ca`, `Cl`, `Mg`, `PT`, `pH`, etc.) with `requires_context=true`.

Suggested generated outputs:

```text
data_resources/generated/lab_terms_candidates.csv
data_resources/generated/lab_terms_rejected.csv
data_resources/generated/pdf_alias_links.csv
data_resources/lab_terms_curated.csv
```

### Step 3 — check `abbreviation.txt` for additional aliases

Responsibilities for the supplemental abbreviation stage:

1. Read `abbreviation.txt` line by line after PDF-derived aliases have already been generated.
2. Extract `abbr` and `gloss`.
3. Apply curated lab/non-lab allowlist and blocklist.
4. Compare each accepted abbreviation against the aliases already extracted from the two PDFs.
5. Add the abbreviation only when it provides a useful additional alias for a lab name, e.g. `ABG` for `Khí máu động mạch`, `BUN` for `Ure/Urê`, `SGPT` for `ALT`.
6. Link each accepted abbreviation to an existing `canonical_key` from `combined_lab_catalog.csv` by exact alias, normalized expansion match, parenthetical PDF alias, or manual mapping.
7. Do **not** create parser seeds directly from raw abbreviations unless the abbreviation is linked to a canonical lab concept or explicitly approved during curation.
8. Mark short/ambiguous supplemental aliases (`K`, `Na`, `Ca`, `Cl`, `Mg`, `PT`, `pH`, `cr`, etc.) with `requires_context=true`.

Additional output of this stage:

```text
data_resources/generated/abbreviation_alias_links.csv
```

### Step 4 — human review / curation

Review columns:

```csv
term,canonical_key,canonical_name,source,category,specimen,requires_context,decision,review_notes
```

Set `decision` to:

- `accept`
- `accept_context_required`
- `reject_non_lab`
- `reject_unit`
- `reject_ambiguous`
- `defer_guideline_check`

### Step 5 — integrate into parser

Parser load path should return a structured resource object:

```python
@dataclass(frozen=True)
class LabTermEntry:
    term: str
    canonical_key: str
    canonical_name: str
    source: str
    category: str
    specimen: str
    requires_context: bool
    priority: int
```

Then dictionary seed creation should use entries instead of bare strings.

### Step 6 — validate

Validation should be independent of old build scripts:

1. Unit tests for PDF extraction/merge using frozen sample text snippets from both PDFs.
2. Unit tests for PDF-derived alias extraction, including prefix stripping and parenthetical aliases.
3. Unit tests for canonical deduplication in `combined_lab_catalog.csv` (`Ure`/`Urê`, `Creatinin`/`Creatinine`, `Calci`/`Canxi`).
4. Unit tests for parsing `abbreviation.txt` and adding only supplemental abbreviation aliases that link to combined-catalog canonical keys.
5. Unit tests for context-gated short seeds:
   - `k 5.4` in lab context -> accepted.
   - `k` in ordinary prose -> rejected.
   - `cr (creatinine) 1.2` -> accepted.
   - `pt` in an English phrase without lab result -> rejected.
6. Offset round-trip tests remain mandatory:
   - `doc.raw_text[start:end] == candidate.text`.
7. Regression tests on real examples from input notes:
   - `canxi là 12.0; canxi ion hóa 6.8`
   - `cr (creatinine) 1.2`
   - `Ure tăng từ 69 lên 91 mg/dl ... photpho 8.4`
   - `alp 185`
   - `ferritin là bình thường`
   - `ck 58`

---

## 9. Recommended first curated dictionary slice

If we want a safe first version before the full metadata design is implemented, expand the flat `lab_seed_terms.csv` with this curated slice:

```text
ABG
ACTH
AFP
ALP
Amylase
APTT
ASLO
Ca
CK
CK-MB
Cl
CRP hs
CRPhs
D-Dimer
D dimer
ESR
Ferritin
Feritin
FT3
FT4
G6PD
GGT
Hb
HCO3
Hct
HDL
HDL-C
LDH
LDL
LDL-C
MCH
MCHC
MCV
Mg
Na
NT-proBNP
PCT
PT
PTT
RF
SGOT
SGPT
TSH
Ure
Urê
acid uric
acid uric máu
albumin
albumin máu
alp
amylase
axit uric
bilirubin gián tiếp
bilirubin toàn phần
bilirubin trực tiếp
calci
calci ion hóa
calci toàn phần
canxi
canxi ion hóa
canxi toàn phần
cholesterol
cholesterol toàn phần
ck
ck-mb
clo
cr
creatinin
creatinin máu
d-dimer
điện giải
điện giải niệu
ferritin
feritin
ggt
globulin
hba1c
hemoglobin
huyết đồ
khí máu
khí máu động mạch
ldh
lipase
lipase máu
magie
magiê
máu lắng
natri
phospho
photpho
proteid máu
protein toàn phần
sắt
triglycerid
ure
ure máu
urê
```

Important: the following in this slice should be flagged `requires_context=true` in the richer system, even if kept in a flat CSV temporarily:

```text
Ca, Cl, Mg, Na, PT, cr, ck, Hb, Hct
```

`K/k` already exists and should also be context-gated in the rebuilt parser.

---

## 10. Decision summary

Recommended architecture decision:

1. Combine `lab_med_ministry.pdf` and `lab_list.pdf` into one `combined_lab_catalog.csv` before building parser-facing resources.
2. Use `lab_med_ministry.pdf` as the preferred official/canonical source for biochemical lab names.
3. Use `lab_list.pdf` as practical local alias enrichment and to recover concise terms commonly used in notes.
4. Extract aliases from the combined PDF catalog first; then use `abbreviation.txt` only as a supplemental source to add missing lab-name aliases after lab/non-lab filtering and canonical-linking.
5. Do not dump every extracted PDF term or abbreviation into the matching dictionary. Generate candidates, then curate into accepted/context-required/rejected groups.
6. Feed `lab_parser` from the final curated combined-and-aliased resources (`lab_terms_curated.csv` and `lab_canonical_map.csv`), not from raw PDFs or raw abbreviation lines.
7. Upgrade the parser from bare string seeds to metadata-backed `LabTermEntry` seeds so short abbreviations can be safely used without increasing false positives.
8. Add overlap and context logic before result pairing, because a larger dictionary will make overlaps and ambiguous abbreviations much more frequent.

---

## 11. Expected benefits

- Higher recall for lab names in Vietnamese notes, especially chemistry/electrolytes/renal/liver/cardiac markers.
- Better support for abbreviation-heavy clinical notes (`cr`, `bun`, `ck`, `alp`, `hba1c`, `pt/ptt`, `abg`).
- Better canonical grouping for downstream linking or normalization.
- Lower false-positive risk than a raw catalog dump because ambiguous abbreviations are explicitly context-gated.
- Easier future maintenance: new aliases can be traced back to a source and reviewed systematically.
