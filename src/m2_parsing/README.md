# M2 — Chuẩn hóa dữ liệu LaTeX

M2 đọc dữ liệu đã có từ M1, xử lý LaTeX, trích xuất tài liệu tham khảo và tạo các bảng dữ liệu để sử dụng ở các bước tiếp theo. Code hiện tại kết hợp các sửa lỗi chuẩn hóa của Rev13 và FIX143; phiên bản pipeline là **14**.

Bài hoặc phiên bản không có LaTeX được ghi nhận là `empty` và bỏ qua phần chuẩn hóa tương ứng. M2 không tải bổ sung dữ liệu thiếu của M1.

## Chạy trên Google Colab

1. Mở [notebooks/m2/M2.ipynb](../../notebooks/m2/M2.ipynb) bằng Colab.
2. Đổi `RANGES` ở cell cấu hình, ví dụ `[3]` hoặc `[3, 4, 5]`, rồi chọn **Runtime → Run all**. Notebook tự tải code M2 từ GitHub vào máy Colab, cố định tại commit `21aa3f3c32cbe528b02ca5d45a7475ae3099155f` (Rev14); không cần chép project lên Drive. Muốn dùng phiên bản code khác, đổi `CODE_COMMIT` thành commit đã được đẩy lên GitHub.
3. Xác thực Google Drive khi Colab yêu cầu. `M1_PARENT_ID` mặc định là thư mục checkpoint chung của nhóm; tài khoản chạy phải có quyền đọc và thư mục đó phải chứa `range_N_dev` cho từng range được chọn. Nếu dùng thư mục khác, thay ID tương ứng.

Kết quả mặc định được lưu ở `MyDrive/M2_STANDARDIZED_REV14`; workspace nằm ở `MyDrive/M2_STANDARDIZED_WORKSPACE_REV14`. Giữ workspace nếu muốn tiếp tục sau khi Colab ngắt. Mỗi range mặc định cần đủ 5.000 bài M1. Nếu code hoặc checkpoint thay đổi, chọn thư mục output mới để giữ kết quả cũ.

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
