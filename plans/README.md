# Plans

Thư mục này chứa tài liệu kế hoạch/implementation notes cho ViClinicalIE, được tổ chức theo trạng thái và chức năng.

## Cấu trúc

```text
plans/
├── README.md
├── active/
│   ├── 00_overview/
│   ├── 01_pipeline/
│   ├── 02_models/
│   ├── 03_rules_parsers/
│   └── 04_evaluation_checkpoints/
└── archive/
    ├── 2026-07-10/
    └── legacy/
```

## Active plans

### 00_overview

- [`active/00_overview/00_architecture_hybrid_vihealthbert.md`](active/00_overview/00_architecture_hybrid_vihealthbert.md) — kiến trúc hybrid rule-based + ViHealthBERT.

### 01_pipeline

- [`active/01_pipeline/01_offset_preserving_preprocessing.md`](active/01_pipeline/01_offset_preserving_preprocessing.md) — implementation log cho preprocessing bảo toàn offset.

### 02_models

- [`active/02_models/01_vihealthbert_ner.md`](active/02_models/01_vihealthbert_ner.md) — implementation/workflow/trace cho ViHealthBERT NER layer.

### 03_rules_parsers

- [`active/03_rules_parsers/01_drug_parser.md`](active/03_rules_parsers/01_drug_parser.md) — drug parser.
- [`active/03_rules_parsers/02_lab_parser.md`](active/03_rules_parsers/02_lab_parser.md) — lab parser base plan/log.
- [`active/03_rules_parsers/03_lab_seeds_update.md`](active/03_rules_parsers/03_lab_seeds_update.md) — update lab seeds.
- [`active/03_rules_parsers/04_dictionary_rules.md`](active/03_rules_parsers/04_dictionary_rules.md) — dictionary/rules plan.
- [`active/03_rules_parsers/05_lab_parser_update.md`](active/03_rules_parsers/05_lab_parser_update.md) — lab parser update.

### 04_evaluation_checkpoints

- [`active/04_evaluation_checkpoints/01_checkpoint_1.md`](active/04_evaluation_checkpoints/01_checkpoint_1.md) — checkpoint/evaluation notes.

## Archive

### 2026-07-10

- [`archive/2026-07-10/todo_2026-07-10.md`](archive/2026-07-10/todo_2026-07-10.md) — todo cũ ngày 2026-07-10.

### Legacy

- [`archive/legacy/architecture_legacy.md`](archive/legacy/architecture_legacy.md) — kiến trúc legacy.
- [`archive/legacy/candidate_linking_plan.md`](archive/legacy/candidate_linking_plan.md) — candidate linking plan legacy.

## Quy ước đặt tên

- File active dùng prefix số để thể hiện thứ tự đọc trong từng nhóm.
- Tên file dùng `snake_case`, mô tả chủ đề chính.
- Tài liệu không còn là plan chính được đặt trong `archive/`.
