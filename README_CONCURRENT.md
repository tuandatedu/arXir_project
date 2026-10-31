# M1 arXiv — Crawler concurrent có giới hạn

README này mô tả chế độ tải đồng thời có kiểm soát của M1. Crawler xử lý nhiều paper trong cùng một batch, nhưng vẫn giới hạn tốc độ request tới arXiv.

## Cách hoạt động

- `run_arxiv_only.py` nhận `--workers 1..4`; mặc định là 1.
- Các worker xử lý paper song song **bên trong một batch**. Các batch vẫn chạy lần lượt, và kết quả được ghi theo thứ tự ID.
- Mỗi worker dùng một `requests.Session` riêng.
- Bộ điều phối dùng chung đảm bảo thời điểm bắt đầu hai request arXiv cách nhau ít nhất 3,1 giây. Khóa chỉ được giữ khi đặt lịch request và cập nhật bộ đếm; worker không giữ khóa trong lúc chờ response hoặc đọc body.
- Retry và thời gian chờ do 429/5xx được chia sẻ giữa các worker.
- Tăng workers có thể giúp chồng lấp thời gian chờ tải xuống, nhưng không đảm bảo crawler chạy nhanh hơn. Không tăng tốc độ request arXiv.

## Cài đặt và kiểm tra

Chạy tại thư mục gốc repository:

```bash
python -m pip install -r src/m1_crawling/requirements-crawler.txt
python -m pytest -q tests/test_arxiv_crawler.py tests/test_runtime_tracking.py tests/test_concurrent_crawler.py
python -m src.m1_crawling.run_arxiv_only --range 5 --workers 3 --batch-size 50 --preview
```

Lệnh cuối chỉ xem trước range, không tải paper. Các bài kiểm tra trên chạy offline.

## Chạy trong Colab

1. Chạy cell SET UP để clone hoặc cập nhật đúng branch chứa code mới.
2. Mount Google Drive và giữ nguyên `RANGE_ID`, `BATCH_SIZE`, `DATA_DIR` đang dùng cho checkpoint hiện tại.
3. Trong cell cấu hình, đặt `MAX_WORKERS = 3` nếu muốn thử 3 worker. Giá trị hợp lệ là 1–4; mặc định 1.
4. Chạy lại các cell định nghĩa hàm sau khi cập nhật source.

Không đổi `BATCH_SIZE` trong thư mục đã có checkpoint. Có thể thay đổi `MAX_WORKERS` khi tiếp tục.

## Fast Crawl

CLI chạy tối đa N batch chưa có checkpoint hợp lệ:

```bash
python -m src.m1_crawling.run_arxiv_only --range 5 --workers 3 --batch-size 50 --next 10
```

Trong notebook:

```python
fast_crawl(batches=10)
```

`batches=10` là tối đa 10 batch, mỗi batch có tối đa `BATCH_SIZE` ID. Crawler bỏ qua checkpoint hoàn chỉnh; checkpoint lỗi discovery có thể được thử lại. Cell `crawl_batches(batches=...)` của notebook còn lấy reference và tạo bảng theo luồng M1.

## Recovery

Recovery chỉ xử lý batch đã có checkpoint và còn paper lỗi; không tạo batch mới. Paper có trạng thái `ok` hoặc `no_tex` không bị tải lại.

```python
recovery_crawl(batches=100, retries=1, backup_before=False)
```

- `batches=100`: giới hạn tối đa 100 batch lỗi được xử lý.
- `retries=1`: số lần retry HTTP sau lần thử đầu tiên.
- `backup_before=False`: không tạo thêm bản sao archive trước recovery.

## Report và thời gian chạy

```python
summary = export_report()
```

`runtime_history.csv` ghi wall-clock của từng lượt chạy Fast Crawl/Recovery. Không cộng thời gian của các worker để ước tính wall-clock. Dữ liệu lịch sử từ các lượt chạy cũ không được tính lại.

## Giới hạn và lưu ý

- Chỉ chạy **một notebook hoặc process ghi vào cùng `DATA_DIR` tại một thời điểm**.
- Nếu dừng giữa batch, các checkpoint batch đã hoàn thành vẫn được giữ; batch đang chạy có thể cần chạy lại.
- Giới hạn pacing 3,1 giây vẫn áp dụng trên toàn tiến trình, kể cả khi tăng workers.
- `runtime_history.csv` và `metrics.csv` là dữ liệu đo theo từng lượt chạy; `workers_this_run` cho biết số worker được dùng.
- Nên so sánh workers=1 và workers=3 trên các nhóm ID tương đương. Ghi nhận wall-clock và lỗi 429; không giả định concurrent luôn nhanh hơn.

## Cập nhật repository

Commit source code và notebook lên branch nhóm đang dùng. Không commit dữ liệu crawl như `batch_*.tar.gz`, `batch_*.json`, thư mục reference hoặc dữ liệu trong Google Drive.

Sau khi cập nhật GitHub, chạy lại cell SET UP trong Colab để lấy source mới. Giữ nguyên thư mục checkpoint và cấu hình batch để tiếp tục an toàn.
