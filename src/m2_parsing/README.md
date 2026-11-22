# M2 — Chuẩn hóa dữ liệu LaTeX

M2 đọc dữ liệu đã có từ M1, xử lý LaTeX, trích xuất tài liệu tham khảo và tạo các bảng dữ liệu để sử dụng ở các bước tiếp theo. Code hiện tại kết hợp các sửa lỗi chuẩn hóa của Rev13 và FIX143; phiên bản pipeline là **14**.

Bài hoặc phiên bản không có LaTeX được ghi nhận là `empty` và bỏ qua phần chuẩn hóa tương ứng. M2 không tải bổ sung dữ liệu thiếu của M1.

## Chạy trên Google Colab

1. Chép thư mục `arXir_project` đã cập nhật lên Google Drive.
2. Mở [notebooks/m2/M2.ipynb](../../notebooks/m2/M2.ipynb) bằng Colab.
3. Chạy các cell theo thứ tự. Ở cell cấu hình, sửa `PROJECT_ROOT` nếu thư mục project trên Drive không nằm tại `/content/drive/MyDrive/arXir_project`.
4. Xác thực Google Drive khi Colab yêu cầu. Mặc định notebook chạy range 1 và 2, dùng link checkpoints M1 đã cấu hình sẵn.

Kết quả mặc định được lưu ở `MyDrive/M2_STANDARDIZED_REV14`; workspace nằm ở `MyDrive/M2_STANDARDIZED_WORKSPACE_REV14`. Giữ workspace nếu muốn tiếp tục sau khi Colab ngắt. Notebook dùng code trong project, vì vậy cần chép bản project đã cập nhật lên Drive trước khi chạy.

Khi chạy lại, M2 kiểm tra dữ liệu nguồn, code, phiên bản thư viện và checksum trước khi dùng lại kết quả. Kết quả Rev13/FIX143 trước đây được lưu riêng và không tự động trở thành cache của revision 14.

## Chạy trên máy

Chạy các lệnh sau từ thư mục gốc `arXir_project`:

```bash
python -m pip install -r src/m2_parsing/requirements.txt
python -m src.m2_parsing.run_m2 --batch-dir PATH_TO_CHECKPOINTS --working-dir PATH_TO_WORKING --tables-dir PATH_TO_OUTPUT --workers 2 --resume
```

Với nhiều range, đặt các thư mục `range_1_dev`, `range_2_dev` trong cùng một thư mục M1 rồi chạy:

```bash
python -m src.m2_parsing.drive_runner --ranges 1 2 --local-checkpoints PATH_TO_M1 --output PATH_TO_OUTPUT --workspace PATH_TO_WORKSPACE --workers 2
```

Thay các giá trị `PATH_TO_...` bằng đường dẫn thật. `drive_runner` mặc định kiểm tra 5.000 bài mỗi range; dùng `--expected-papers` nếu chạy bộ dữ liệu thử nhỏ hơn. Xem toàn bộ tùy chọn bằng `python -m src.m2_parsing.run_m2 --help` hoặc `python -m src.m2_parsing.drive_runner --help`.

## Kết quả

Mỗi range có ZIP `M2_range_N_tables.zip` chứa:

- `elements.jsonl`: nội dung và các thành phần trích từ bài.
- `hierarchy.jsonl`: quan hệ giữa các thành phần.
- `bibtex.jsonl`: tài liệu tham khảo đã chuẩn hóa.
- `metrics_m2.json`: thống kê và trạng thái xử lý.

Các file `quality_report.json`, `paper_status.jsonl` và báo cáo đi kèm giúp kiểm tra kết quả và những bài cần xem thêm. Nếu một range thất bại, xem `FAILED_range_*.json` trong thư mục output và `parser_full.log` trong workspace.

## Cấu trúc code

- `gather.py`, `cleanup.py`, `hierarchy.py`, `tex_spans.py`: thu thập và xử lý LaTeX.
- `bibitem.py`, `bibliography_fields.py`, `dedup.py`: trích xuất, chuẩn hóa và gộp tài liệu tham khảo.
- `pipeline.py`, `batch_pipeline.py`, `cache.py`: xử lý bài, batch và lưu kết quả để tiếp tục chạy.
- `quality_checks.py`, `diagnostics.py`, `audit.py`: kiểm tra và tạo báo cáo.
- `run_m2.py`, `drive_runner.py`: các lệnh chạy M2.
- [notebooks/m2](../../notebooks/m2): notebook chạy M2 và notebook báo cáo.

Các kiểm thử M2 nằm trong `tests/test_m2_*.py`; dữ liệu kiểm thử bibliography có 485 mẫu từng được rà soát.
