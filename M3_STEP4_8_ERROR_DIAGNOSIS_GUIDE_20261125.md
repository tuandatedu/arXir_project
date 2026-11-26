# M3 — Bước 4.8: Chẩn đoán lỗi `Positive-count/GT mismatch` (READ-ONLY)

## 1. Triệu chứng đã xác minh

Lệnh `M3_STEP4_8_BUILD_PREDICTIONS_READONLY.py` đã chấm điểm đủ **4.185.238** candidate pairs trong Train, tạo trạng thái nhớ cho **142.125** BibTeX queries, sau đó báo:

```text
[FAILED] ValueError: Positive-count/GT mismatch: ('2609.39989', 'ref5')
```

**Không phải lỗi training hoặc inference**: sự cố xảy ra ở `finalize_partition()`, nơi code yêu cầu mỗi query có `groundtruth_arxiv_id` khác null phải có **đúng 1 dòng label=1** trong candidate matrix. Code ban đầu kiểm tra:

```python
n_pos == (1 if rec['gt'] is not None else 0)
```

Theo nguồn nhãn manual đang có trên Google Drive (`labels/manual/2609.39989.json`), `('2609.39989','ref5')` mang `groundtruth_arxiv_id='2503.23037'`. File rà nhãn `2609.39989.csv` cũng có gợi ý `2503.23037` cho `ref5`. Nhưng **chưa đọc được chính `train_pairs.parquet` đang nằm ở máy người dùng**, nên CHƯA biết là:

1. GT `2503.23037` không xuất hiện trong candidate pool → 0 Positive; hoặc
2. cùng arXiv ID ứng viên xuất hiện lặp lại → từ 2 Positive trở lên.

Các kịch bản này cần sửa theo **hai cách khác nhau**. Không nên tự sửa nhãn, bỏ kiểm tra, hoặc đổi GT thành null khi chưa biết nguyên nhân.

## 2. Công cụ mới: `M3_STEP4_8_DIAGNOSE_TRAIN_READONLY.py`

- Chỉ đọc cột `arxiv_id`, `citation_key`, `ref_arxiv_id`, `groundtruth_arxiv_id`, `label` trong **Train** frozen.
- Kiểm tra SHA-256 đúng `f9cf5e...27f` và số dòng 4.185.238.
- Chẩn đoán **toàn bộ query** Train, không chỉ `ref5`.
- Phân biệt `KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL`, `DUPLICATED_POSITIVE_CANDIDATE_ID`, `PAIR_LABEL_GT_INCONSISTENT`, v.v.
- Không tải `.joblib`, không gọi `predict_proba`, không đọc Validation hoặc Test, không ghi vào Train.
- Xuất mới `train_gt_diagnostic.json` ở `outputs/`.

## 3. Hướng dẫn chạy trong PowerShell

Giải nén gói chẩn đoán vào project root:

`C:\1_HDD\IntroDS_M3\arXir_project_ML`

Với `.venv` đang kích hoạt:

```powershell
python .\M3_STEP4_8_DIAGNOSE_TRAIN_READONLY.py --selftest
```

Sau đó:

```powershell
python .\M3_STEP4_8_DIAGNOSE_TRAIN_READONLY.py `
  --repo . `
  --out-dir .\outputs\step48_train_gt_diagnosis_01
```

Nếu thư mục output đó đã tồn tại, tăng hậu tố thành `..._02` — script không ghi đè.

Sau khi chạy, gửi lại **phần cuối Terminal** (FOCUS, STATUS COUNTS, ANOMALIES) và, tốt nhất, tệp:

`outputs\step48_train_gt_diagnosis_01\train_gt_diagnostic.json`

## 4. Cách đọc kết quả và bước xử lý

| Chẩn đoán | Ý nghĩa | Xử lý tiếp theo |
|---|---|---|
| `KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL` | Nhãn có arXiv ID đúng nhưng ID đó không nằm trong danh sách candidate đã đóng băng | Kiểm tra provenance và quy tắc all-negative/GT-null; quyết định cách bảo toàn GT trước khi xuất predictions, báo rõ số lượng ngoại lệ |
| `DUPLICATED_POSITIVE_CANDIDATE_ID` | Cùng ID ứng viên đúng xuất hiện nhiều dòng (một query có nhiều Positive) | Kiểm tra duplicate trong ma trận m×n và chọn chiến lược xuất **candidate IDs duy nhất**; không đơn giản bỏ kiểm tra |
| `PAIR_LABEL_GT_INCONSISTENT` | `label` không khớp `(ref_arxiv_id == groundtruth_arxiv_id)` | Cần đánh giá dữ liệu nguồn và quy trình xây dựng nhãn |
| `INCONSISTENT_GT_WITHIN_QUERY` | Một BibTeX entry có nhiều giá trị GT | Sai lệch dữ liệu; phải xem lại upstream |

Theo [statement M3](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/), các ứng viên là các references được crawl của **cùng** citing publication. Khi có match hợp lệ trong candidate pool, phải có **một positive**; khi không có, hàng candidate là **all-negative**. Do đó, cách sửa đúng phải dựa trên thực tế candidate pool chứ không ép số lượng Positive bằng 1.

**Cấm làm lúc này:** Train lại LR13/LightGBM, tune theo Test, tự động đổi nhãn GT, sửa Parquet frozen, hoặc bỏ toàn bộ kiểm tra chỉ để script báo PASS.
