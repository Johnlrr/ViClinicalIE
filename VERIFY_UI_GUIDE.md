# NER-5 Data Verification UI

## Cách sử dụng

### Bước 1: Chạy server

```powershell
cd D:\ViClinicalIE
python scripts\verify_ner5_ui.py
```

Server sẽ hiển thị:
```
✅ NER-5 Verify UI running at http://localhost:5000
📊 Loaded 9 pilot samples
👉 Open your browser and go to http://localhost:5000
🛑 Press Ctrl+C to stop
```

### Bước 2: Mở trình duyệt

Mở Chrome/Firefox và truy cập:
```
http://localhost:5000
```

### Bước 3: Review từng mẫu

UI sẽ hiển thị:
- **Sample ID**: Tên mẫu hiện tại
- **Text**: Câu gốc với entities được highlight màu
- **Entities**: Danh sách entities tìm thấy
- **Checklist**: 4 tiêu chí cần kiểm tra
- **Notes**: Ghi chú nếu có vấn đề

Màu sắc entities:
- 🟠 **TRIỆU_CHỨNG** (cam)
- 🔵 **CHẨN_ĐOÁN** (xanh dương)
- 🟣 **THUỐC** (tím)
- 🟢 **TÊN_XÉT_NGHIỆM** (xanh lá)
- 🔴 **KẾT_QUẢ_XÉT_NGHIỆM** (đỏ)

### Bước 4: Review actions

Cho mỗi mẫu, bạn có thể:
- **Previous/Next**: Chuyển mẫu
- **Approve**: Mẫu OK
- **Reject**: Mẫu có vấn đề
- **Notes**: Ghi lý do reject

### Bước 5: Export kết quả

Sau khi review xong tất cả mẫu (hoặc đủ mẫu), bấm **Export**. File JSON sẽ được tải về với format:

```json
{
  "timestamp": "2026-07-24T10:30:00.000Z",
  "approved": 8,
  "rejected": 1,
  "unreviewed": 0,
  "reviews": {
    "clean_diagnosis_00000": "approved",
    "clean_drug_00001": "rejected"
  },
  "notes": {
    "clean_drug_00001": "Boundary bao qua context"
  }
}
```

### Bước 6: Cập nhật config

Nếu **approved >= 7/9** (>75%):

```powershell
# Cập nhật configs/ner5.yaml
```

Thêm vào file:
```yaml
human_review:
  status: approved
  reviewer: "Your Name"
  date: "2026-07-24"
  notes: "Reviewed 9 pilot samples. 8 approved, 1 minor issue."
```

Sau đó rebuild:
```powershell
python scripts\build_ner5_data.py
```

Nếu **rejected > 2/9**:
```yaml
human_review:
  status: revision_required
  reviewer: "Your Name"
  date: "2026-07-24"
  notes: "Issues found: <chi tiết>"
```

## Troubleshooting

**Port 5000 đã được sử dụng:**
```powershell
# Sửa PORT trong scripts/verify_ner5_ui.py thành 5001 hoặc 8000
```

**Browser không load được:**
- Kiểm tra server có đang chạy không
- Thử refresh (F5)
- Thử browser khác

**Không thấy samples:**
- Kiểm tra `data/processed/ner_v2/manifest.json` có tồn tại không
- Kiểm tra console log trong browser (F12)

## Tiếp theo

Sau khi approve → NER-6 (Fine-tuning decision)
