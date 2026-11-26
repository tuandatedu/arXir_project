# M3 — Chia chung 5 Range & chạy Machine Learning (26/11/2026)

**Phạm vi:** R1–R5 của một nhóm; mỗi `arxiv_id` là một *publication*, một đơn vị chia dữ liệu. **Không được chia ngẫu nhiên từng pair**. Tập Test mới chỉ được đánh giá bằng script ở Bước 3 sau khi đã huấn luyện và khóa LR13 trên Train/Validation mới.

**Đã làm thực tế ngay trong phiên này:** tải và kiểm tra 5 ZIP nhãn tự động + 25 JSON manual; xác nhận 18.523 publications không trùng; dựng lại split cũ bằng `M3-matching/split.py` seed 42; tạo phân vùng thống nhất và khóa file `global5_publication_split.csv` bằng SHA-256 trong `global5_split_manifest.json`. Không đổi bất cứ nhãn GT nào.

**Chưa thể làm trong phiên này:** chạy **training thật và đánh giá Test thật** của toàn bộ năm Range do chưa có đủ 5 bộ *features candidate-pairs có thể xử lý được bằng PyArrow* và `.joblib` huấn luyện mới trên môi trường này. Các script dưới đây được viết để thực thi trên máy Windows/`.venv` của bạn; kiểm thử cú pháp và kiểm tra logic MRR bằng dữ liệu giả lập đã PASS, còn đường chạy Parquet end-to-end cần kiểm chứng từ log local.

## 1. Kết quả chia chung đã tạo

| Partition | Publications | BibTeX queries |
|---|---:|---:|
| train | 18.519 (23 manual, 18.496 auto) | 790.739 |
| valid | 2 (1 manual, 1 auto) | 64 |
| test | 2 (1 manual, 1 auto) | 59 |
| **Tổng** | **18.523** | **790.862** |

Publication Test mới (chưa được dùng trong Validation/Test cũ): **manual `2604.01323` (R3)** và **auto `2603.18656` (R5)**. Validation mới: **manual `2604.00125` (R4)** và **auto `2604.03553` (R3)**. Bốn publication này đều thuộc **Train gốc** của các Range 2–5, không thuộc Train R1 (đã dùng train các model cũ), cũng không nằm trong các Validation hoặc Test cũ. Việc chọn sử dụng RNG seed 42 trên tập publication chưa qua đánh giá để giảm rò rỉ từ các lần audit trước. Đây là **một thí nghiệm mới**, không sử dụng Test R1 trước đó làm Test chính thức của nhóm.

Dữ liệu nguồn `dataset_pairs.parquet` của từng Range giữ nguyên như ở Drive; **không dùng `train_pairs.parquet` gốc của riêng từng Range**, vì đó là kết quả chia cũ và thiếu publications thuộc Validation/Test gốc.

## 2. Chuẩn bị đủ 5 nguồn dữ liệu cặp

Mỗi Range cần đúng file `prepared_dataset/dataset_pairs.parquet` (full candidate-pair dataset, chứa cả ba partition cũ):

| Range | Nguồn Drive chính xác | Kích thước byte để kiểm tra |
|---|---|---:|
| R1 | [dataset_pairs R1](https://drive.google.com/file/d/1D7Pnfx4uqd6kVnfHbqLKSg_O0VLGjieZ/view) | 41.555.823 |
| R2 | [dataset_pairs R2](https://drive.google.com/file/d/1lzDzogqbe3aYb1V6mP3QsCzs-T_AwFAi/view) | 45.996.673 |
| R3 | [dataset_pairs R3](https://drive.google.com/file/d/13G6r0gEjMuEQXjjA8ZrFLo-JcboLP_kk/view) | 47.229.007 |
| R4 | [dataset_pairs R4](https://drive.google.com/file/d/1wvTV4nA17kPGphin58vVCP8lrRdEvug1/view) | 43.019.402 |
| R5 | [dataset_pairs R5](https://drive.google.com/file/d/1kAMJxazZnkfiXUY9iM316j36tx_dqBFj/view) | 50.228.908 |

Nếu đã có file nguồn tương ứng trên máy thì không cần tải lại. Đề xuất lưu bản sao **bên ngoài** các thư mục frozen cũ:

```
C:\1_HDD\IntroDS_M3\arXir_project_ML\
  M3_GLOBAL5_PREPARE_READONLY.py
  M3_GLOBAL5_TRAIN_VALIDATE.py
  M3_GLOBAL5_TEST_AND_EXPORT.py
  global5_split_manifest.json
  global5_publication_split.csv
  data\m3\global5_input\
    range_1\dataset_pairs.parquet
    range_2\dataset_pairs.parquet
    range_3\dataset_pairs.parquet
    range_4\dataset_pairs.parquet
    range_5\dataset_pairs.parquet
```

Không đổi tên `dataset_pairs.parquet` của từng Range vì script sẽ từ chối sai tên hoặc sai kích thước nguồn.

## 3. BƯỚC 1 — Tạo Train/Valid/Test chung, chưa train/test

Mở PowerShell trong `C:\1_HDD\IntroDS_M3\arXir_project_ML`, kích hoạt `.venv`, sau đó:

```powershell
python .\M3_GLOBAL5_PREPARE_READONLY.py `
  --split .\global5_publication_split.csv `
  --manifest .\global5_split_manifest.json `
  --r1 .\data\m3\global5_input\range_1\dataset_pairs.parquet `
  --r2 .\data\m3\global5_input\range_2\dataset_pairs.parquet `
  --r3 .\data\m3\global5_input\range_3\dataset_pairs.parquet `
  --r4 .\data\m3\global5_input\range_4\dataset_pairs.parquet `
  --r5 .\data\m3\global5_input\range_5\dataset_pairs.parquet `
  --out-dir .\outputs\global5_prepared_01
```

Script kiểm tra hashes của split map, tên/kích thước nguồn, tập publication, partition cũ, label, 13 features, không có duplicate candidate, và số lượng queries từ nhãn. Bản `.parquet` mới và `global5_prepared_manifest.json` chỉ ghi vào thư mục output mới.

**Chú ý:** Nếu chỉ có `train_pairs.parquet` ở Range 2–5 thì không đủ để tái chia; phải lấy `dataset_pairs.parquet` full.

## 4. BƯỚC 2 — Huấn luyện LR13 và LightGBM13 trên Train chung, chỉ xem Validation

```powershell
python .\M3_GLOBAL5_TRAIN_VALIDATE.py `
  --prepared-dir .\outputs\global5_prepared_01 `
  --out-dir .\outputs\global5_models_01 `
  --num-threads 4
```

- B1 (Title) và B2 (Title+Author+Year) không cần fit.
- LR13 dùng 13 features, `StandardScaler` + `LogisticRegression(lbfgs,max_iter=1000,class_weight=None,random_state=42)`, mô hình **chính được ấn định trước Test**.
- LightGBM13 dùng cùng 13 features; `300 trees`, `learning_rate=0.05`, `num_leaves=31`, `min_child_samples=100`, `reg_lambda=1.0`, `seed=42`; mô hình đối chứng.
- Script tạo memmap trên ổ đĩa để giảm RAM khi train khoảng hàng chục triệu candidate pairs; vẫn cần kiểm tra bộ nhớ trống (đặc biệt khi huấn luyện LightGBM) và dung lượng ổ đĩa.
- Script **không có tham số Test** và không mở `test_pairs.parquet`. Kết quả tạo `lr13_model.joblib`, `lgbm13_model.joblib`, `global5_pretest_model_lock.json`, `validation_query_metrics.csv`, `validation_top5.csv`.

**Nếu xảy ra lỗi bộ nhớ:** Không giảm Train, không đổi GT hoặc mở Test để cải thiện điểm. Gửi log lỗi để chỉnh giải pháp kỹ thuật (batch, RAM, thư mục lưu tạm) và vẫn giữ protocol cố định.

## 5. BƯỚC 3 — Đánh giá Test mới, chỉ sau khi Bước 2 PASS

```powershell
python .\M3_GLOBAL5_TEST_AND_EXPORT.py `
  --phase test `
  --prepared-dir .\outputs\global5_prepared_01 `
  --model-dir .\outputs\global5_models_01 `
  --split .\global5_publication_split.csv `
  --manifest .\global5_split_manifest.json `
  --out-dir .\outputs\global5_test_01
```

Xuất `global5_test_metrics.json`, `global5_test_query_metrics.csv`, `global5_test_top5.csv`. Báo cáo MRR@5 **riêng manual và auto** và đối chiếu B1/B2/LR13/LGBM13. Không lựa chọn lại mô hình từ Test.

## 6. BƯỚC 4 — Xuất toàn bộ `predictions.parquet` đúng 9 cột

```powershell
python .\M3_GLOBAL5_TEST_AND_EXPORT.py `
  --phase export `
  --prepared-dir .\outputs\global5_prepared_01 `
  --model-dir .\outputs\global5_models_01 `
  --split .\global5_publication_split.csv `
  --manifest .\global5_split_manifest.json `
  --out-dir .\outputs\global5_predictions_01
```

Xuất file `predictions.parquet` gồm **790.862 rows dự kiến**, mỗi query một row, đúng cột `arxiv_id`, `partition`, `citation_key`, `groundtruth_arxiv_id`, `cand_1`..`cand_5` cùng `global5_predictions_manifest.json` và file kiểm tra known-GT-outside-pool. Ghi theo batch và giữ thứ tự tie-break gốc; **không bịa một candidate có GT trong khi candidate pool không chứa nó**.

Khi thành công, có thể lọc publication theo cột `arxiv_id` bằng `global5_publication_split.csv` để mỗi thành viên lấy Range mình phụ trách, mà không cần chia Train/Valid/Test lần thứ hai.

## 7. Giới hạn và trạng thái

- Manifest và CSV **đã tạo và kiểm tra trên nhãn nguồn thật**. Các scripts PyArrow/LightGBM trên dữ liệu Parquet full 5 Range **chưa được chạy thành công trong phiên này**. Khi chạy trên máy Windows, phải kiểm tra log trước khi nói hoàn tất toàn bộ ML.
- Kiểm tra nguồn chỉ ở mức kích thước byte từ Drive khi chạy prepare; lần chạy chuẩn bị sẽ ghi SHA-256 thực tế của 5 file vào manifest mới. Nếu file nguồn thay đổi cần đối chiếu và khóa bản mới, không silently tiếp tục.
- Model mới khác `.joblib` Range 1; **không thay** mô hình Range 1 cũ khi chạy.
- Nhãn automatic dựa trên DOI-first + title/author/year heuristic, có hạn chế label dependence. Ground Truth có thể khác null dù ứng viên đúng không nằm trong candidate pool. Với GT-null, RR=0 theo protocol.
- Test toàn nhóm mới chưa được sử dụng cho tuning. Kết quả Test R1 cũ là báo cáo phát triển, không dùng làm Test chính thức của thí nghiệm chung.
- Không thực hiện tích hợp pipeline chung/Hugging Face ở bước này; chỉ làm phần ML và dataset split.

**Statement:** https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/ — chia theo publication, đúng một manual+auto Validation, một manual+auto Test, Train còn lại; MRR@5; predictions chỉ chứa publications dùng cho matching, 9-column schema.
