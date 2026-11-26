# M3 — Bước 4.6: Chốt mô hình và protocol trước Test

**Ngày:** 25/11/2026  
**Phạm vi:** Phần cá nhân Machine Learning & Evaluation (không tích hợp pipeline nhóm)  
**Nguồn code & artifacts:** [`tuandatedu/arXir_project`, nhánh `M3-model`, commit `7f542abd88f4864b58bbca3fe183a0a4b7e7628b`](https://github.com/tuandatedu/arXir_project/tree/7f542abd88f4864b58bbca3fe183a0a4b7e7628b)  
**Trạng thái:** **ĐÃ CHỐT LỰA CHỌN/PROTOCOL Ở MỨC TÀI LIỆU, CHỜ XÁC MINH JOBLIB LOCAL — CHƯA ĐƯỢC MỞ TEST**.

## 1. Kết quả đã kiểm tra được

- LR13 và LGBM13 cùng được fit trên **4.185.238 Train pairs Range 1** và sử dụng **cùng 13 numeric features** (loại `doi_match`). Tài liệu metrics cho LR13: `n_iter=17`, `max_iter=1000`; LGBM13: `n_estimators=300`, `actual_trees=300`.
- Trên Range 1 Validation: cả B1, B2, LR13, LGBM13 cùng `MRR@5(all)=38/53≈0,716981`. Trên 5 Range Validation: cả bốn cùng `MRR@5(micro)=158/281≈0,562278`.
- Mọi Positive query trong các bộ Validation đã kiểm tra đều ở Top-1 với cả bốn phương pháp, nhưng **113/123 GT-null query** có ít nhất hai phương pháp đưa ra Top-1 khác nhau. Không biết lựa chọn nào đúng trên GT-null từ nhãn hiện có.
- `scripts/run_weighted_baseline.py::rank_candidates` cố định score giảm dần, nếu đồng điểm giữ candidate xuất hiện trước trong query bằng `mergesort`. `train_logistic_regression.py` và `train_lightgbm.py` đều gọi chung quy tắc này.
- **GitHub không lưu `lr13_model.joblib` và `lgbm13_model.joblib`.** Không thể chứng minh byte-level model/scaler hoặc dự đoán sau load nếu chưa có artifact trên máy người dùng.

## 2. Quyết định chọn mô hình chính

| Vai trò | Phương pháp | Lý do |
|---|---|---|
| **Mô hình ML chính đề xuất khóa** | **Logistic Regression 13 features (LR13)** | Không thua LGBM13 trên Validation đã kiểm tra; đơn giản, ít phức tạp hơn và dễ diễn giải hệ số; đáp ứng phần ML của đề bài |
| Đối chứng tối giản | B1 — title-only | Cho thấy sức mạnh của độ tương đồng tiêu đề |
| Đối chứng thủ công | B2 — weighted title/author/year | So sánh mức bổ sung tín hiệu tác giả/năm |
| Đối chứng ML phi tuyến | LGBM13 | Kiểm tra liệu mô hình phức tạp hơn có làm tốt hơn hay không; **chưa có lợi thế MRR** |

**Không tuyên bố LR13 cao điểm hơn LGBM13 hoặc Baselines.** Chọn LR13 làm mô hình ML đại diện theo nguyên tắc đơn giản, dễ giải thích khi các kết quả MRR bằng nhau. Quyết định này **được lập trước Test**, không dựa vào Test.

## 3. Cấu hình khóa — chưa mở Test

- **Git commit:** `7f542abd88f4864b58bbca3fe183a0a4b7e7628b`.
- **Training:** Range 1 frozen 23/11, 4.185.238 pairs; SHA256 `f9cf5eb22ad1aad07b2db3135c26802cf00cd06fffc9e183dbaa3275c7dec27f`.
- **Validation:** Range 1 frozen 23/11, 4.261 pairs; SHA256 `f62896841d6f3b5ebbc38ea098873eaa4daacaa34a22d5c4efc7c5cde49fd294`.
- **Feature order:** `title_levenshtein`, `title_token_sort`, `title_token_set`, `title_jaccard`, `title_exact`, `title_len_diff_ratio`, `author_jaccard`, `author_first_match`, `author_any_match`, `year_diff`, `year_exact`, `year_missing`, `cite_count`.
- **Bỏ hẳn khỏi model input:** DOI, label, GT, citation key, source/candidate IDs, partition.
- **LR13:** `StandardScaler` fit trên Train; `LogisticRegression(solver='lbfgs', max_iter=1000, class_weight=None, random_state=42)`; không train lại.
- **LGBM13:** giữ nguyên 300 trees, learning rate 0.05, 31 leaves, min_child_samples 100; không train lại.
- **Score:** xác suất lớp Positive (`predict_proba`, class 1) dùng để sắp xếp **các candidates đã có trong cùng publication**; giảm dần score; đồng điểm theo thứ tự dòng gốc của file frozen; Top-5, nếu ít hơn 5 thì giữ số lượng thực có. Không áp threshold hoặc abstention rule mới.
- **MRR@5:** RR=1/rank nếu Positive nằm Top-5, ngược lại 0; GT-null RR=0 theo code hiện tại. Báo riêng `MRR@5(all)`, `MRR@5(positive-only)`, `Hit@1`, `Hit@5`, số Positive/GT-null.
- **Khi Test cuối:** sau khóa, báo cáo MRR riêng hai publications **manual** và **automatic** theo seminar, không dùng kết quả Test để đổi thuật toán/hyperparameters/threshold.

File cấu hình máy đọc: `M3_STEP4_6_PROTOCOL_FREEZE_20261125.json`.

## 4. Kiểm tra local còn thiếu — đã tạo script READ-ONLY

Script: `M3_STEP4_6_PREFLIGHT_READONLY.py` (không cần Codex). Nó thực hiện:

1. Khóa đúng 4 file code đã publish theo Git blob SHA; không ghi đè file nguồn.
2. Kiểm tra SHA256, số dòng và schema của **Train/Validation Range 1**, không thể vô tình mở Test vì chỉ chấp nhận `train_pairs.parquet` và `valid_pairs.parquet`.
3. Load **joblib do nhóm tự tạo** (pickle: không dùng artifact không đáng tin), kiểm tra pipeline, scaler đã fit toàn bộ Train, classes, 13 features đúng thứ tự, LR intercept/số vòng, LightGBM số cây.
4. Scoring toàn bộ 4.261 Validation pairs bằng hai model đã lưu; tính lại Top-5 theo đúng stable tie-break và so với **đủ 265 dòng** của mỗi `validation_top5.csv` đã publish, gồm ID, rank, label, score (có tolerance số thực).
5. Tự kiểm thử quy tắc Top-5 với 1, 3, 5, 6 candidates đồng score.
6. Chỉ khi toàn bộ kiểm tra PASS mới tạo thư mục mới và hai file `verification_report.json`, `verified_protocol_lock.json` với checksum model. **Không** train/fit lại, không cập nhật repo, không mở Test.

### Cách chạy trên Windows PowerShell

Tải **hai file** `.py` và `.json` vào **thư mục gốc của repository local** (thư mục chứa `scripts/`, `outputs/`, `data/`). Mở terminal PowerShell tại thư mục đó:

```powershell
python .\M3_STEP4_6_PREFLIGHT_READONLY.py `
  --repo . `
  --train ".\data\m3\range_1_frozen_20261123\prepared_dataset\train_pairs.parquet" `
  --valid ".\data\m3\range_1_frozen_20261123\prepared_dataset\valid_pairs.parquet" `
  --protocol ".\M3_STEP4_6_PROTOCOL_FREEZE_20261125.json" `
  --out-dir ".\outputs\step46_local_verify_20261125_01"
```

Đường dẫn trên lấy từ metrics các lần chạy trước; nếu bạn có thư mục khác, chỉnh tham số **chỉ theo vị trí thật của file**, không đổi snapshot. Thư mục output phải chưa tồn tại, nếu cần chạy lại hãy đổi tên output mới; không ghi đè log cũ.

**Nếu PASS:** Gửi lại `verified_protocol_lock.json`, `verification_report.json` hoặc nội dung terminal để xác nhận hoàn tất bước 4.6.  **Nếu FAIL:** Không mở Test; gửi nguyên lỗi để phân tích và sửa điều kiện không phù hợp (không tự sửa dữ liệu frozen).

## 5. Những giới hạn chưa thể kết luận từ đây

- Chưa thể trực tiếp đọc file `.joblib` có trên máy của người dùng hoặc độc lập chạy inference trên Parquet gốc trong môi trường này. Kiểm tra code/CSV/JSON và script kiểm thử giả lập **không thay thế preflight local**.
- Chưa có audit đầy đủ về source-publication overlap giữa Train Range 1 với Validation các Range 2–5. Không viết rằng thí nghiệm 5 Range là *completely independent cross-range generalization* trước khi kiểm.
- Chưa xác minh tỷ lệ đúng thực tế trên GT độc lập; nhãn auto là DOI-first hybrid có title/author/year fallback. Không gọi GT-null là negative chứng thực.
- Chưa chốt được tổ chức Test các Range 2–5 theo yêu cầu nhóm. Bản freeze này chốt **mô hình và quy tắc**, Test chính thức ưu tiên Range 1; các Range khác cần giữ nguyên nguyên tắc không tune bằng Test.

## 6. Trạng thái cuối bước

- **ĐÃ LÀM:** lựa chọn mô hình chính, freeze feature/scoring/MRR/cấu hình, truy vết code/metrics, tạo manifest và preflight script; script đã `py_compile` và vượt qua synthetic ranking/sentinel metrics test (53 queries, 4.261 pairs).
- **CHỜ KIỂM CHỨNG TRÊN MÁY:** byte-level `.joblib` + full Validation reproduction; chỉ sau PASS mới gọi là **model/protocol lock đã xác minh**.
- **CHƯA LÀM:** mở Test, huấn luyện lại, sửa nhãn/source, tích hợp pipeline chung, xuất Hugging Face/poster.
