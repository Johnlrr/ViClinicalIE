# Lab Parser v2 — Metadata-backed dictionary, context gating, overlap resolution & expanded coverage

Ngày thực hiện: 2026-07-11
Phạm vi: layer `6.4 Lab parser` trong [`0_architecture.md`](../00_overview/00_architecture_hybrid_vihealthbert.md#64-lab-parser).

## 1. Tóm tắt thay đổi

Lab parser v2 nâng cấp từ dictionary phẳng (`List[str]` seeds) lên dictionary metadata hóa (`LabTermEntry`), bổ sung context gate cho alias mơ hồ, phân giải overlap, mở rộng unit, và canonical identity trong trace. Backward-compatible: code dùng `Sequence[str]` cũ vẫn chạy.

| Thành phần | v1 | v2 |
|---|---|---|
| Dictionary format | `lab_seed_terms.csv` (flat strings) | `lab_terms_curated.csv` (10-column metadata) |
| Canonical grouping | Không | `canonical_key` → `lab_canonical_map.csv` |
| Context gate | Không | `requires_context` + `_has_lab_context()` |
| Overlap resolution | Không | `resolve_overlapping_aliases()` |
| Units | 7 nhóm | ~22 nhóm (IU/L, ng/L, pmol/L, FL...) |
| Trace metadata | seed_source, seed_confidence | + canonical_key, canonical_name, category, specimen, source_detail, requires_context |
| Tests | 19 v1 | 38 (19 v1 + 19 v2) |
| Data resources | `lab_seed_terms.csv` 45 dòng | + `lab_terms_curated.csv` 30+ curated rows + `lab_canonical_map.csv` 150+ canonical entries |

## 2. Chi tiết thay đổi

### 2.1 Dataclass mới: `LabTermEntry`

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

Mỗi entry là một *alias* (bề mặt `term`) gắn với canonical identity (`canonical_key` + `canonical_name`), có nguồn gốc (`source`/`source_detail`), phân loại (`category`/`specimen`), ưu tiên (`priority`) và flag context gate (`requires_context`).

### 2.2 `LabSeed` mở rộng

```python
@dataclass(frozen=True)
class LabSeed:
    start: int
    end: int
    text: str
    seed_source: str          # "lab_dictionary" | "vihealthbert_ner"
    seed_term: str
    seed_confidence: float = 1.0
    entry: Optional[LabTermEntry] = None  # metadata khi dictionary-backed
```

`entry` là optional — khi đến từ NER, `entry=None`; khi đến từ dictionary, mang metadata đầy đủ.

### 2.3 `LabParseTrace` bổ sung canonical fields

```python
@dataclass(frozen=True)
class LabParseTrace:
    # ... v1 fields ...
    canonical_key: Optional[str] = None
    canonical_name: Optional[str] = None
    source_detail: Optional[str] = None
    category: Optional[str] = None
    specimen: Optional[str] = None
```

Helper `_entry_trace_kwargs(seed)` điền các field này từ `seed.entry`.
### 2.4 `load_lab_dictionary(csv_path)` — loader mới

```python
def load_lab_dictionary(csv_path: str) -> List[LabTermEntry]:
```

- Đọc `lab_terms_curated.csv` với `csv.DictReader`.
- Parse boolean `requires_context`, integer `priority`.
- **Graceful degradation**: nếu file không tồn tại, trả về `[]` và parser fallback sang bare-string `Sequence[str]`.

### 2.5 `build_term_lookup(entries)` — normalized lookup

```python
def build_term_lookup(entries: Sequence[LabTermEntry]) -> Dict[str, LabTermEntry]:
```

- Key = `normalize_for_matching(entry.term)`.
- Priority tie-break: `priority` cao hơn thắng; cùng priority thì term dài hơn thắng.
- Dùng trong `parse_lab_candidates()` khi `lab_entries` được cung cấp.

### 2.6 Context gate cho alias mơ hồ

Mới: `/src/lab_parser.py` lines 333–367

```python
_CONTEXT_GATE_LINE_MARKERS = (
    "xét nghiệm", "cận lâm sàng", "kết quả", "điện giải",
    "khí máu", "chem", "cbc", "đông máu", "huyết học",
)

_CONTEXT_GATE_SECTION_KEYWORDS = (
    "cận lâm sàng", "kết quả xét nghiệm", "laboratory",
    "lab_result_section",
)

def _has_lab_context(line: Line, doc: ClinicalDocument) -> bool:
```

Gate kiểm tra 3 lớp:
1. **Section/subsection type** chứa keyword (`kết quả xét nghiệm`, `cận lâm sàng`...).
2. **Line text** chứa lab marker (`xét nghiệm`, `chem`, `cbc`...).
3. **Left/right context** (dòng kề trên/dưới) chứa lab marker.

Trong `parse_lab_candidates()`, các seed có `requires_context=True` bị loại nếu không có lab context:

```python
if seed.entry and seed.entry.requires_context:
    if line is not None and not _has_lab_context(line, doc):
        continue  # skip
```

Các alias context-gated trong `lab_terms_curated.csv` (hiện tại): `HCO3`, `CO2`, `Hct`, `Hb`, `Mg`, `Na`, `pH`, `PT`, `TT`, `K`, `Ca`, `Cl`, `cr`, `CK`...

### 2.7 Overlap resolution

Mới: `/src/lab_parser.py` lines 369–414

```python
def resolve_overlapping_aliases(
    aliases: List[str],
    lookup: Dict[str, LabTermEntry],
) -> List[str]:
```

Thuật toán:
- Sắp xếp alias theo `(độ dài, priority)` giảm dần.
- Duyệt: nếu alias A là substring của alias B (dài hơn) **và** cùng `canonical_key` → A bị subsumed.

Ví dụ thực tế:
- `bilirubin` (ngắn) bị subsumed bởi `bilirubin toàn phần` (dài, cùng `canonical_key="bilirubin_toan_phan"`).
- `canxi` bị subsumed bởi `canxi ion hóa`.
- `crp` bị subsumed bởi `crp hs`.

### 2.8 Expanded `LAB_UNITS`

Từ 7 nhóm → ~22 nhóm, bổ sung:

```
iu/l, miu/l, µiu/ml, ng/l, pmol/l, nmol/l, µmol/l,
fl, pg, coi
```

*(Các unit cũ vẫn giữ: mg/dl, mmol/l, g/dl, g/l, ng/ml, pg/ml, mcg/dl, µg/dl, µmol/l, mEq/l, %, ml, g, mg, mcg, µg, mmol, µmol, fr, mm, cm, mm/h, mmHg, ...)*

### 2.9 Backward compatibility

`parse_lab_candidates()` signature mới:

```python
def parse_lab_candidates(
    doc: ClinicalDocument,
    lab_terms: Sequence[str],
    ner_candidates: Optional[Sequence[SpanCandidate]] = None,
    lab_entries: Optional[Sequence[LabTermEntry]] = None,
) -> List[SpanCandidate]:
```

- `lab_entries=None` → parser chạy hoàn toàn như v1 với bare strings.
- `lab_entries` được cung cấp → lookup metadata, context gate, overlap resolution active.
## 3. Data resources mới

### 3.1 `lab_terms_curated.csv`

Đường dẫn: [`data_resources/lab_terms_curated.csv`](../../data_resources/lab_terms_curated.csv)

| Column | Ý nghĩa | Ví dụ |
|---|---|---|
| `term` | Bề mặt alias | `APTT`, `PT`, `Hb`, `Na`, `bạch cầu đa nhân` |
| `canonical_key` | Key canonical ID | `aptt`, `pt`, `hemoglobin`, `natri`, `pmn` |
| `canonical_name` | Tên hiển thị canonical | `APTT`, `PT (thời gian prothrombin)`, `Hemoglobin`, `Natri` |
| `source` | Provenance | `manual_curation` (phase 1), sau mở rộng từ `lab_list_pdf`/`lab_med_ministry` |
| `source_detail` | Chi tiết | `plan_section_9`, sau ghi chú row ID |
| `category` | Nhóm | `chemistry`, `hematology`, `coagulation`, `blood_gas`, `endrocrine` |
| `specimen` | Loại mẫu | `blood`, `urine`, `csf` |
| `requires_context` | Context gate flag | `true` cho `K`, `Na`, `Ca`, `cr`, `CK`, `Hb`, `Hct`, `PT`, `Mg`, `pH`, `HCO3`, `CO2`... |
| `priority` | Ưu tiên (cao hơn = thắng) | `5` (curated > 0 bare) |
| `notes` | Ghi chú curation | `manual_curation` |

Hiện tại 30+ rows (manual từ plan section 9). Pipeline mở rộng lên ~939 terms theo kế hoạch.

### 3.2 `lab_canonical_map.csv`

Đường dẫn: [`data_resources/lab_canonical_map.csv`](../../data_resources/lab_canonical_map.csv)

150+ canonical entries với `canonical_key`, `canonical_name`, `category`, `default_specimen`, `aliases` (pipe-delimited), `external_source_notes` (trace tới PDF row).

Nguồn: `lab_med_ministry.pdf` + `lab_list.pdf` (theo plan `1_plan_update_lab_seeds.md`).
- `_make_dummy_entry(term)` tạo `LabTermEntry` giả khi có bare string nhưng cần trace entry (dùng trong `_dictionary_lab_seeds`).