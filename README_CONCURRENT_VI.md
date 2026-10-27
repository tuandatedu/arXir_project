# M1 arXiv — Bản concurrent có giới hạn

## Thay đổi

- `run_arxiv_only.py`: thêm `--workers 1..4` (mặc định 1), xử lý đồng thời các bài **bên trong** một batch. Batch vẫn chạy tuần tự; kết quả được ghi theo thứ tự ID.
- `arxiv_http.py`: mỗi worker có session riêng; **chỉ khóa lúc điều phối thời điểm bắt đầu request**, không khóa lúc đợi phản hồi hoặc đọc dữ liệu. Các request vẫn cách nhau tối thiểu 3,1 giây trên toàn tiến trình; retry/backoff/Retry-After dùng cooldown chung.
- Recovery: giữ nguyên bản sửa chỉ xử lý checkpoint đã tồn tại có lỗi; không crawl thêm batch mới. Phiên bản `ok` và `no_tex` không bị tải lại.
- Checkpoint `.tar.gz`, `.json`, các trường của `crawl_records.jsonl`, report CSV và `runtime_history.csv` không đổi. `metrics.csv` có thể có thêm `workers_this_run`.
- `tests/test_concurrent_crawler.py`: kiểm thử offline về concurrent, thứ tự, Recovery, các luồng HTTP đồng thời và giới hạn tốc độ chung.

## Cách cập nhật GitHub

Chép các file đã sửa vào **nhánh `M1-update`** và commit/push. File notebook ở gốc ZIP có thể mở trực tiếp trong Colab. Không commit dữ liệu `batch_*.tar.gz`, `batch_*.json` hoặc thư mục Google Drive lên GitHub.

```bash
python -m pip install -r src/m1_crawling/requirements-crawler.txt
python -m pytest -q tests/test_arxiv_crawler.py tests/test_runtime_tracking.py tests/test_concurrent_crawler.py
python -m src.m1_crawling.run_arxiv_only --range 5 --workers 3 --batch-size 50 --preview
```

Trong Colab, chạy lại cell SET UP để `git pull` phiên bản mới (hoặc clone lại nếu đã đổi thư mục). Sau đó mount Drive và giữ nguyên `RANGE_ID`, `BATCH_SIZE` (ví dụ 10 hoặc 50), `DATA_DIR` đã dùng. Thêm `MAX_WORKERS = 3` ở cell cấu hình. Không cần xóa checkpoint cũ.

### Fast Crawl

```python
fast_crawl(batches=10)  # tối đa 10 batch mới, mỗi batch `BATCH_SIZE` ID
```

### Recovery

```python
recovery_crawl(batches=100, retries=1, backup_before=False)
```

Recovery sẽ chỉ xử lý các checkpoint **đã tồn tại** và có `failed > 0`. `batches=100` là giới hạn số batch có lỗi được xử lý, không phải số bài hoặc số lần thử. `retries=1` là số lần HTTP retry sau lần thử đầu. Để quay về xử lý tuần tự, đặt `MAX_WORKERS = 1`.

### Report

```python
summary = export_report()
```

`runtime_history.csv` tiếp tục ghi thời gian chạy thực tế; **không cộng thời gian từng worker** để suy ra wall-clock. Số liệu lịch sử trước bản cập nhật không tự thay đổi.

## Giới hạn

- Đây là **concurrent ở cấp bài báo**, các lượt tải HTTP có thể chồng lấp, nhưng request mới vẫn phải chờ giới hạn 3,1 giây chung. Tốc độ không nhất thiết tăng nếu bị giới hạn bởi arXiv hoặc số phiên bản mỗi bài.
- Chỉ một notebook/process ghi vào cùng `DATA_DIR` tại một thời điểm. Nếu dừng giữa batch, checkpoint cuối cùng đã hoàn thành vẫn còn; batch đang dở có thể phải chạy lại.
- Không đổi `BATCH_SIZE` trong cùng thư mục checkpoint; thay đổi `MAX_WORKERS` được.
- Test chạy offline, chưa đo tốc độ thực tế trên arXiv. Nên benchmark 1 vs 3 worker trên các nhóm ID tương đương và xem lỗi 429.

## HTTP pacing fix (v2)

- Each worker has its own requests.Session. The global lock covers only request-start pacing and counters, not the response body.
- Starts of arXiv requests remain at least 3.1 seconds apart across all workers; 429/5xx cooldown is shared.
- Multiple workers may wait for responses and stream sources simultaneously. This does not guarantee a speedup; network behavior, server throttling and file sizes vary.
- Keep BATCH_SIZE unchanged for existing checkpoints. Recovery still touches only existing failed batches.
