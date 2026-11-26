# M3 — Bước 4.7: Test Evaluation (Range 1)

- Protocol: `IntroDS_M3_R1_LR13_PreTest_2026-11-25_v1` (fixed before Test)
- Primary ML model: **LR13**; comparators: B1, B2, LGBM13
- Git commit: `7f542abd88f4864b58bbca3fe183a0a4b7e7628b`
- Test SHA-256: `ed3beef0b3a40891a9bf0edbd3e922897ad4adac76efef182567801a1a3fc05d`
- Methodology: one BibTeX query, candidate pool within same citing publication; score descending, ties retain input order.
- MRR@5: GT-null contributes RR=0; positive-only MRR / Hit@1 / Hit@5 also provided.

## MRR@5 per publication (official primary + comparators)

| Method | Label origin | Publication | Queries | Positive | GT-null | MRR@5 | Positive-only MRR@5 |
|---|---|---|---:|---:|---:|---:|---:|
| B1 | auto | `2610.01287` | 61 | 39 | 22 | 0.639344 | 1.000000 |
| B1 | manual | `2610.01936` | 22 | 22 | 0 | 1.000000 | 1.000000 |
| B2 | auto | `2610.01287` | 61 | 39 | 22 | 0.639344 | 1.000000 |
| B2 | manual | `2610.01936` | 22 | 22 | 0 | 1.000000 | 1.000000 |
| LR13 | auto | `2610.01287` | 61 | 39 | 22 | 0.639344 | 1.000000 |
| LR13 | manual | `2610.01936` | 22 | 22 | 0 | 1.000000 | 1.000000 |
| LGBM13 | auto | `2610.01287` | 61 | 39 | 22 | 0.639344 | 1.000000 |
| LGBM13 | manual | `2610.01936` | 22 | 22 | 0 | 1.000000 | 1.000000 |

## MRR@5 tổng hợp theo query (bổ sung, không thay thế hai publication)

| Method | Queries | Positive | GT-null | Micro MRR@5 |
|---|---:|---:|---:|---:|
| B1 | 83 | 61 | 22 | 0.734940 |
| B2 | 83 | 61 | 22 | 0.734940 |
| LR13 | 83 | 61 | 22 | 0.734940 |
| LGBM13 | 83 | 61 | 22 | 0.734940 |

## Giới hạn diễn giải

- `MRR@5=1` trên nhóm Positive không chứng minh mô hình chính xác trên mọi citation hoặc trên dữ liệu thực tế.
- Automatic Ground Truth theo quy tắc DOI-first, title/author/year fallback; có nguy cơ label dependence.
- GT-null chưa phải bằng chứng độc lập rằng ngoài thực tế không có tài liệu khớp.
- 2 source publications ở Test Range1; không diễn giải như một nghiên cứu với hàng trăm independent publications.
- Không chọn lại mô hình/hyperparameters dựa trên Test; đây là báo cáo cố định, không phải điểm điều chỉnh tiếp.
- File `test_lr13_predictions_ONLY.csv` mới là prediction Test Range1; chưa đủ final `predictions.parquet` train/valid/test.
