# arXiv Project — HCMUS Intro-DS

Project xử lý dữ liệu bài báo arXiv qua ba milestone: thu thập dữ liệu (M1), chuẩn hóa LaTeX và tài liệu tham khảo (M2), sau đó chuẩn bị dữ liệu matching (M3). Yêu cầu môn học được mô tả trong [lab book](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/).

| Phần | Công việc | Hướng dẫn |
| --- | --- | --- |
| M1 | Thu thập metadata, source LaTeX và references từ Semantic Scholar | [README M1](src/m1_crawling/README.md) · [tài liệu bổ sung](docs/m1/README.md) |
| M2 | Đọc source M1, chuẩn hóa nội dung, cấu trúc và bibliography | [README M2](src/m2_parsing/README.md) |
| M3 | Làm sạch, gán nhãn, tạo đặc trưng và dữ liệu cho matching | [README M3](src/m3_matching/README.md) · [hướng dẫn matching](src/m3_matching/MATCHING_M3.md) |

Notebook được chia theo milestone trong [notebooks/](notebooks/README.md). Các module Python nằm trong `src/`, kiểm thử trong `tests/`, cấu hình và schema dùng chung trong `src/common/`.

## Cài đặt

Python 3.10 trở lên. Từ thư mục gốc project:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r src/requirements.txt
```

Nếu chỉ chạy M2, có thể cài `python -m pip install -r src/m2_parsing/requirements.txt`. Key Semantic Scholar có thể đặt trong biến môi trường `S2_API_KEY` khi chạy M1. Không đưa key, `assigned_ids.txt` hay dữ liệu chạy vào Git.

## Cách chạy

**M1:** xem [hướng dẫn M1](src/m1_crawling/README.md) và [notebook M1](notebooks/m1/M1.ipynb). Các notebook khác cho crawler và Semantic Scholar được liệt kê trong mục lục notebook. Với danh sách ID cục bộ, CLI nhận file UTF-8 có một arXiv ID mỗi dòng:

```bash
python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
```

**M2:** [notebook M2](notebooks/m2/M2.ipynb) đã cấu hình checkpoint M1 cho range 1 và 2. Cần đưa project đã cập nhật lên Google Drive, sửa `PROJECT_ROOT` trong notebook rồi chạy các cell. Bài hoặc phiên bản không có LaTeX được ghi nhận là empty và bỏ qua phần chuẩn hóa. Xem [README M2](src/m2_parsing/README.md) để chạy local, tiếp tục batch và đọc kết quả. Code hiện tại dùng pipeline revision 14; kết quả Rev13/FIX143 cũ được lưu riêng.

**M3:** notebook [M3_matching.ipynb](notebooks/m3/M3_matching.ipynb) và [hướng dẫn matching](src/m3_matching/MATCHING_M3.md) mô tả các bước làm sạch, gán nhãn, tạo đặc trưng và bộ dữ liệu. Các bước model, đánh giá và xuất dữ liệu vẫn còn phần chưa triển khai; `run_m3.py` chưa phải CLI hoàn chỉnh.

## Dữ liệu và đầu ra

M1 sử dụng working corpus và checkpoint theo batch. M2 tạo `elements.jsonl`, `hierarchy.jsonl`, `bibtex.jsonl` và `metrics_m2.json`; khi chạy qua notebook, mỗi range có ZIP bảng và các báo cáo kiểm tra riêng. M3 sử dụng dữ liệu M1/M2 cùng nhãn manual và automatic. Xem hướng dẫn từng milestone để biết layout cụ thể.

`data/` là thư mục dữ liệu local và được Git bỏ qua. Không commit checkpoint, kết quả chạy hoặc thông tin đăng nhập vào repo.

## Kiểm thử

```bash
python -m pip install pytest
python -m pytest -q tests
```

Có thể chạy riêng kiểm thử M2 bằng `python -m pytest -q tests/test_m2_*.py` trên shell hỗ trợ mở rộng wildcard, hoặc chọn các file kiểm thử cụ thể. Kiểm thử không thay thế việc rà soát kết quả khi chạy trên dữ liệu thật.
