# IntroDS — Kiểm chứng Bước 4.7 & Chuẩn bị Bước 4.8

**Ngày:** 25/11/2026  
**Phạm vi:** M3 — Machine Learning & Evaluation — **Range 1**. Không gộp 5 Range, không tích hợp pipeline chung, không đăng Hugging Face.

## 1. Những gì đã được kiểm tra độc lập từ 5 file upload

Nguồn: `test_query_metrics.csv`, `test_summary.md`, `test_top5_comparison.csv`, `test_lr13_predictions_ONLY.csv`, `test_metrics.json` do thành viên cung cấp sau khi chạy Bước 4.7.

| Hạng mục | Kiểm chứng |
|---|---|
| Query-level metrics | 332 rows = 83 queries × 4 phương pháp, mỗi `(arxiv_id, citation_key, method)` duy nhất |
| Top-5 | 1660 rows = 83 queries × 4 methods × 5 candidates |
| Schema Test-only predictions | 83 rows, 9 cột theo statement, `partition=test` |
| Top-5 LR13 ↔ predictions CSV | **415/415 candidate slots trùng** |
| Candidate rank | Rank 1–5, score giảm dần, không có duplicate candidate IDs trong từng Top-5 |
| RR@5 | Tính lại từ từng query khớp `test_metrics.json` và `test_summary.md` |
| Ground Truth | 61 Positive, 22 GT-null, không mâu thuẫn với `has_positive` trong các file |
| Chênh lệch ranking | 19/22 GT-null queries có >=2 phương pháp khác Top-1; 61/61 Positive queries thì Top-1 thống nhất |

### Kết quả Test Range 1

| Publication | Nguồn nhãn | Queries | Positive | GT-null | MRR@5 mỗi phương pháp |
|---|---|---:|---:|---:|---:|
| `2610.01287` | Auto | 61 | 39 | 22 | **0,6393442623** |
| `2610.01936` | Manual | 22 | 22 | 0 | **1,0000000000** |
| **Micro query** | Cả hai | **83** | **61** | **22** | **0,7349397590** |

Cả B1, B2, LR13 và LightGBM13 có cùng giá trị trong bộ file này. **Không kết luận** LightGBM/LR13 vượt Baseline; GT-null RR=0 không chứng minh thực tế không có match. Đơn vị nguồn Test chỉ 2 citing publications.

> Mức độ kiểm chứng: Các phép đối chiếu này **đọc 5 file đầu ra**, không truy cập model `.joblib` hay Parquet Test nằm trên máy thành viên. Log Bước 4.6/4.7 đã báo thành công; việc tự xác nhận raw model/dataset trên máy là công việc riêng.

## 2. Đầu ra cần đạt của Bước 4.8 theo statement M3

Chỉ với những publication tham gia supervised matching trong Train, Valid và Test, tạo **một dòng cho mỗi BibTeX entry** với schema (theo đúng thứ tự):

1. `arxiv_id`: string, non-null.
2. `partition`: dictionary-encoded string, giá trị `train`/`valid`/`test`.
3. `citation_key`: string, non-null.
4. `groundtruth_arxiv_id`: nullable string.
5. `cand_1`, `cand_2`, `cand_3`, `cand_4`, `cand_5`: nullable string, xếp giảm dần theo score, đồng điểm ưu tiên dòng candidate xuất hiện trước trong file đã đóng băng.

Bước này dùng **LR13 đã khóa**; B1/B2/LightGBM13 tiếp tục nằm trong đánh giá so sánh, không thêm cột vào `predictions`.

**Giới hạn quan trọng:** File `predictions.parquet` tạo ở đây là **Range 1, ba split**. Nó chưa thay thế bảng predictions cuối cùng của **toàn bộ 5 Range / nhóm**. Chưa sinh năm bảng dữ liệu khác của Hugging Face, chưa tích hợp code chung.

## 3. Sử dụng bộ script

### A. Chuẩn bị

Giải nén ZIP vào thư mục project:

`C:\1_HDD\IntroDS_M3\arXir_project_ML`

Phải có các file đã được giữ nguyên:

- `outputs/lr13_full_20261125_01/lr13_model.joblib`
- `outputs/lr13_full_20261125_01/validation_top5.csv`
- `outputs/step46_local_verify_20261125_01/verified_protocol_lock.json`
- `outputs/step47_test_r1_20261125_01/test_metrics.json`
- `data/m3/range_1_frozen_20261123/prepared_dataset/train_pairs.parquet`
- `.../valid_pairs.parquet` và `.../test_pairs.parquet`.

Tệp `M3_STEP4_8_FROZEN_TEST_83_ROWS.csv` được đóng gói cùng script; **không sửa** vì đây là bản so sánh với Test đã chấm.

Trong môi trường `.venv` đã chạy được Bước 4.7, cần `numpy`, `pandas`, `scikit-learn`, `joblib` và `pyarrow` (đã có ở project local nếu Bước 4.7 thành công).

### B. Test giả lập trước (không mở dữ liệu thật)

```powershell
python .\M3_STEP4_8_BUILD_PREDICTIONS_READONLY.py --selftest
```

### C. Xuất predictions Range 1

Mở PowerShell tại project root, sau khi kích hoạt `.venv`, chạy:

```powershell
python .\M3_STEP4_8_BUILD_PREDICTIONS_READONLY.py `
  --repo . `
  --lock .\outputs\step46_local_verify_20261125_01\verified_protocol_lock.json `
  --step47-dir .\outputs\step47_test_r1_20261125_01 `
  --out-dir .\outputs\step48_predictions_r1_20261125_01
```

Các kiểm tra an toàn được thực hiện trước: checksum Train/Valid/Test, SHA-256 model LR13, khóa commit, source blob SHA, Test protocol, schema cột và bản 83 Test query đã nộp.

Đầu ra sau khi chạy thành công:

- `outputs/step48_predictions_r1_20261125_01/predictions.parquet`
- `outputs/step48_predictions_r1_20261125_01/predictions_manifest.json`

Script xử lý Train theo các **batch 50.000 rows**, giữ Top-5 theo từng query qua tất cả batch, tie-break bằng **thứ tự dòng gốc**. Kiểm tra toàn bộ query Positive có đúng một cặp có nhãn 1 và mọi query trong một publication có cùng tập ứng viên (qua hai fingerprint 128-bit + số lượng). Tính chất này phù hợp với ma trận m×n của statement; fingerprint có xác suất va chạm cực thấp nhưng không phải kiểm chứng tập hợp chính xác tuyệt đối bằng lưu mọi ID.

Script còn bắt buộc:

- **53 query** Validation cho kết quả Top-5 khớp 265 dòng bản đã khóa ở Bước 4.6;
- **83 query** Test cho kết quả khớp toàn bộ **415 candidate slots** trong bản ở Bước 4.7;
- MRR@5 cho manual/auto Test không thay đổi;
- không có publication trùng giữa Train/Valid/Test;
- Parquet có đúng kiểu string/dictionary/nullable, có đủ ba partition và đúng số dòng dự đoán.

## 4. Giới hạn và các điểm chưa thực hiện

- **Chưa chạy trên 4.185.238 Train pairs thật** trong môi trường ChatGPT: model `.joblib` và Parquet Train/Valid/Test frozen nằm ở máy thành viên. Cần thực thi script trên máy này để tạo và xác nhận `predictions.parquet` cuối của Range 1.
- Ở môi trường tạo công cụ, package `pyarrow` không sẵn và không thể tải thêm; mình đã **compile mã nguồn và chạy selftest thuật toán** thành công, nhưng chưa kiểm chứng độc lập round-trip Parquet. Khi chạy trên máy bạn, script kiểm schema Arrow bằng `ParquetFile` sau khi ghi.
- Nếu script FAIL, giữ nguyên dữ liệu frozen, không sửa Test để làm đẹp điểm; gửi lại log để sửa lỗi tính đúng của script.
- Pseudo-GT có thể phụ thuộc Title/Author/Year (DOI-first hybrid), GT-null không đồng nghĩa confirmed no-match. Đây là giới hạn REPORT.

## 5. Nguồn đối chiếu

- [Statement M3](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/): schema bảng `predictions` và phạm vi Train/Validation/Test.
- [Github arXir_project nhánh M3-model](https://github.com/tuandatedu/arXir_project/tree/M3-model).
- `test_summary.md`, `test_metrics.json` và ba CSV do bạn gửi ngày 25/11/2026.
