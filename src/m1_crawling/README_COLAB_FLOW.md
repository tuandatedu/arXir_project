# Luồng Colab M1 - crawl theo batch và lưu trên Google Drive

Notebook chính: `M1_Colab_Concurrent_Limited.ipynb`. Notebook chạy pipeline M1 đầy đủ qua `run_milestone1`, không chạy crawler checkpoint cũ `run_arxiv_only.py`.

## Chuẩn bị

1. Push code mới và notebook lên branch GitHub mà notebook cấu hình ở biến `BRANCH`.
2. Chọn runtime CPU-only trong Colab.
3. Tạo `assigned_ids.txt` trên Google Drive, mỗi dòng một arXiv ID được giao. Dòng trống và dòng bắt đầu bằng `#` được bỏ qua.
4. Nếu sinh danh sách từ `assigned_ranges.py`, hãy xác minh `cross_month_limit` cho các range đi qua ranh giới tháng trước.

## Chạy crawl

1. Chạy các cell đầu để clone repo, cài thư viện và mount Google Drive.
2. Kiểm tra `IDS_FILE`, `BATCH_SIZE = 50` và thư mục `M1_DIR`.
3. Bỏ dấu `#` ở lệnh `run_m1_batches(max_batches=1)` để chạy batch đầu tiên. Mỗi batch tối đa 50 ID; notebook in tiến độ, số dòng hai bảng và tối đa 5 reference mẫu.
4. Gọi lại `run_m1_batches(max_batches=1)` để chạy batch tiếp theo, hoặc dùng `run_m1_batches(max_batches=None)` để xử lý toàn bộ ID còn lại trong phiên Colab.
5. Nếu Colab bị ngắt, mount lại Drive và chạy cell định nghĩa hàm; checkpoint sẽ giúp bỏ qua ID đã xử lý.
6. Dùng `run_m1_batches(max_batches=1, retry_failed=True)` để thử lại ID có trạng thái `failed` hoặc `partial` gần nhất.

Không chạy hai phiên Colab cùng lúc trên cùng thư mục Drive. Giới hạn tốc độ API vẫn được áp dụng, nên batch 50 có thể mất vài phút hoặc lâu hơn tùy số version và thời gian phản hồi.

## Kết quả trên Drive

Trong thư mục `M1_DIR`:

- `m1_checkpoint.json`: danh sách ID và trạng thái mới nhất, dùng để tiếp tục crawl.
- `corpus/{id}/`: metadata paper, source `.tex`/`.bib` theo version và `references.json`.
- `tables/papers.jsonl`: một dòng cho mỗi paper.
- `tables/references.jsonl`: các reference có arXiv ID.
- `batch_logs/`: metrics của từng batch.
- `metrics_m1.json`: metrics tích lũy sau mỗi batch.
- `m1_missing_checklist.txt`: ID chưa chạy và paper lỗi/chưa hoàn tất cần xem lại.

`references.json` lưu mọi reference, kể cả reference không có arXiv ID. Bảng `references.jsonl` chỉ chứa reference có arXiv ID.

## Kiểm thử offline

Cell cài đặt có tùy chọn `RUN_EXISTING_OFFLINE_TESTS`. Bộ test hiện có chủ yếu kiểm tra `run_arxiv_only.py`; nó không thay thế smoke test qua API cho pipeline M1. Smoke test crawl thật phải dùng ID được giao và sẽ gọi arXiv/Semantic Scholar.
