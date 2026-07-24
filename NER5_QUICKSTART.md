# NER-5 Data Verification - Quick Start

## ✅ Đã hoàn thành

1. **Data generation**: 147 clean + 143 noisy samples
2. **Validation**: Zero errors (offset, duplicate, leakage)
3. **Pilot selection**: 9 representative samples
4. **Verification UI**: Web interface for human review

## 🚀 Bắt đầu verify ngay

### 1. Chạy server (Terminal 1)

```powershell
cd D:\ViClinicalIE
python scripts\verify_ner5_ui.py
```

### 2. Mở browser

Truy cập: **http://localhost:5000**

### 3. Review 9 mẫu

Kiểm tra từng mẫu theo checklist:
- ✓ Boundary đúng?
- ✓ Type đúng?
- ✓ Text tự nhiên?
- ✓ Noise hợp lý?

### 4. Export kết quả

Bấm **Export** để lưu review

### 5. Cập nhật config

Nếu OK (≥7/9 approved):

```yaml
# File: configs/ner5.yaml
human_review:
  status: approved
  reviewer: "Your Name"
  date: "2026-07-24"
  notes: "Reviewed pilot samples, quality OK"
```

Rebuild:
```powershell
python scripts\build_ner5_data.py
```

### 6. Kiểm tra data_ready

```powershell
python -c "import json; print('Ready:', json.load(open('data/processed/ner_v2/manifest.json'))['data_ready'])"
```

Nếu in `Ready: True` → **NER-5 hoàn thành!**

## 📝 Chi tiết đầy đủ

Xem: `VERIFY_UI_GUIDE.md`

## 🔄 Luồng tiếp theo

```
NER-5 (verify) → NER-6 (fine-tuning decision) → Training
```
