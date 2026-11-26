# M3 Range 1 — Bước 4.8 V2: Xử lý 3 known GT nằm ngoài candidate pool

**Ngày:** 25/11/2026  
**Trạng thái:** Đã tạo script V2 và kiểm thử logic giả lập; **chưa** chạy xuất Parquet từ mô hình/data local của người dùng.  
**Phạm vi:** Bản xuất `predictions.parquet` cho Range 1 (train/valid/test), **không** tích hợp pipeline, không thay đổi Train/Valid/Test/model/nhãn.

## 1. Chẩn đoán từ dữ liệu đã khóa

`train_gt_diagnostic.json` do người dùng gửi đã xác nhận toàn bộ 4.185.238 candidate pairs, 142.125 queries từ 3.664 citing publications:

| Phân loại | Số queries |
|---|---:|
| `OK_ONE_POSITIVE` | 75.312 |
| `OK_GT_NULL` | 66.810 |
| `KNOWN_GT_ABSENT_FROM_CANDIDATE_POOL` | **3** |
| **Tổng** | **142.125** |

**3 ngoại lệ chính xác:**

| `arxiv_id` | `citation_key` | `groundtruth_arxiv_id` | Số candidates | Số cặp Positive |
|---|---|---|---:|---:|
| `2609.39989` | `ref5` | `2503.23037` | 268 | 0 |
| `2609.39989` | `ref7` | `2605.25998` | 268 | 0 |
| `2609.39989` | `ref14` | `2608.02880` | 268 | 0 |

GT ở đây **không null** và trùng nhãn manual; nhưng **không có ref ID tương ứng trong candidate matrix đã khóa**. Vì vậy, không phải vấn đề model và **không phải ground truth bị thiếu**. `label=0` trên tất cả candidates là nhất quán với việc true match không tồn tại trong candidate pool. Đây là hạn chế *candidate retrieval coverage*, cần nêu khi báo cáo.

## 2. Bản sửa V2 hoạt động thế nào

Bản gốc `M3_STEP4_8_BUILD_PREDICTIONS_READONLY.py` có điều kiện quá chặt:

```python
n_pos == (1 if gt is not None else 0)
```

V2 vẫn kiểm tra từng candidate phải có `label == int(ref_arxiv_id == groundtruth_arxiv_id)` (với GT non-null), giữ nguyên các bất biến khác, và **chỉ chấp nhận đúng 3 ngoại lệ đã được liệt kê** trong Train. V2 tự đọc file diagnostic, kiểm tra toàn bộ checksum/định danh/loại lỗi/số lượng trước khi chạy.

- `groundtruth_arxiv_id` giữ **nguyên 3 giá trị non-null**, không chuyển thành null.
- `cand_1`...`cand_5` là 5 ứng viên có score cao nhất từ tập **268 IDs có thật**; **không** được thêm GT nhân tạo.
- Train tách riêng `known_gt_absent_from_candidate_pool=3`; `gt_null=66810`, `positives=75312`.
- Nếu Train có ngoại lệ thứ tư, duplicate positive, label/GT mâu thuẫn, hoặc nếu Validation/Test xảy ra ngoại lệ này, **script báo lỗi thay vì bỏ qua**.
- Giữ toàn bộ 13 features, model SHA, Train/Valid/Test SHA, stable Top-5 tie-break, Validation 265 ranks và Test 83 rows/415 candidate slots bất biến.
- Ghi `train_gt_outside_candidate_pool.csv` riêng và đưa cảnh báo vào `predictions_manifest.json`.

Theo **M3 statement** (`https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/`), `groundtruth_arxiv_id` chứa ID đúng *khi đã biết*, còn `cand_1`–`cand_5` chỉ là ứng viên model xếp hạng. Hai loại dữ liệu này không bắt buộc có giao nhau nếu ứng viên không chứa GT. Trong trường hợp này, RR@5 nếu đánh giá trên ba queries là 0 theo quy tắc đánh giá hiện có. Không dùng chúng để thay đổi protocol Test đã khóa.

## 3. Hướng dẫn chạy trên Windows / PowerShell

### A. Giải nén ZIP

Chép hai file vào thư mục gốc:

```
C:\1_HDD\IntroDS_M3\arXir_project_ML
  M3_STEP4_8_BUILD_PREDICTIONS_READONLY_V2.py
  M3_STEP4_8_FROZEN_TEST_83_ROWS.csv
```

**Giữ nguyên file V1** để đối chiếu. File diagnostic hiện có tại:

`outputs\step48_train_gt_diagnosis_01\train_gt_diagnostic.json`

### B. Selftest V2

```powershell
python .\M3_STEP4_8_BUILD_PREDICTIONS_READONLY_V2.py --selftest
```

Cần có dòng:

`[PASS] Synthetic known-GT-outside-pool: rejects unapproved, permits exact audited only`

### C. Xuất thật — output folder mới (không dùng lại V1)

```powershell
python .\M3_STEP4_8_BUILD_PREDICTIONS_READONLY_V2.py `
  --repo . `
  --lock .\outputs\step46_local_verify_20261125_01\verified_protocol_lock.json `
  --step47-dir .\outputs\step47_test_r1_20261125_01 `
  --diagnostic .\outputs\step48_train_gt_diagnosis_01\train_gt_diagnostic.json `
  --out-dir .\outputs\step48_predictions_r1_20261125_v2_01
```

Nếu thư mục `_v2_01` đã tồn tại, đặt tên mới `_v2_02`; không xóa/ghi đè output của lần khác.

### D. Đầu ra sau khi PASS

Trong `outputs\step48_predictions_r1_20261125_v2_01` sẽ có:

- `predictions.parquet`: đúng **9 cột**, một dòng mỗi BibTeX entry thuộc train/valid/test Range 1.
- `predictions_manifest.json`: checksum/model/protocol, thống kê query và thông tin 3 known-GT-absent.
- `train_gt_outside_candidate_pool.csv`: đúng 3 trường hợp ngoại lệ đã kiểm chứng.

Kỳ vọng theo dữ liệu đã chẩn đoán: **Train 142.125 queries**, **Validation 53**, **Test 83** → **tổng 142.261 dòng** nếu không có lỗi phát hiện thêm; số này được xác thực khi script hoàn tất. Test MRR@5 phải bất biến so với Bước 4.7.

## 4. Những gì cần gửi lại để xác nhận

Gửi **log phần cuối** (đặc biệt `SUCCESS`) và `predictions_manifest.json`; có thể gửi thêm `train_gt_outside_candidate_pool.csv`. Không cần gửi Parquet 4 triệu rows đầu vào hoặc joblib.

**Giới hạn:** Trong môi trường tạo script, không có file model `.joblib` local hoặc package `pyarrow`, do đó chỉ tự kiểm thử thuật toán và xác minh diagnostic JSON; không tuyên bố đã chạy Parquet thật. Thực thi local của người dùng mới xác minh chính thức đầu ra.
