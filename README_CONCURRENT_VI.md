# M1 arXiv — Bản concurrent có giới hạn

## Thay đổi

- `run_arxiv_only.py`: thêm `--workers 1..4` (mặc định 1), xử lý đồng thời các bài **bên trong** một batch. Batch vẫn chạy tuần tự; kết quả được ghi theo thứ tự ID.
- `arxiv_http.py`: mỗi worker có session riêng, nhưng toàn bộ HTTP metadata/source và thời gian đọc response được khóa chung. **Chỉ một kết nối hoạt động**, tối thiểu 3,1 giây giữa các request trên toàn tiến trình; retry/backoff/Retry-After dùng cooldown chung.
- Recovery: giữ nguyên bản sửa chỉ xử lý checkpoint đã tồn tại có lỗi; không crawl thêm batch mới. Phiên bản `ok` và `no_tex` không bị tải lại.
- Checkpoint `.tar.gz`, `.json`, các trường của `crawl_records.jsonl`, report CSV và `runtime_history.csv` không đổi. `metrics.csv` có thể có thêm `workers_this_run`.
- `tests/test_concurrent_crawler.py`: kiểm thử offline về concurrent, thứ tự, Recovery, kết nối và rate limit.

## Cách cập nhật GitHub

Chép các file đã sửa vào **nhánh `M1-update`** và commit/push. File notebook ở gốc ZIP có thể mở trực tiếp trong Colab. Không commit dữ liệu `batch_*.tar.gz`, `batch_*.json` hoặc thư mục Google Drive lên GitHub.

```bash
python -m pip install -r src/m1_crawling/requirements-crawler.txt
python -m pytest -q tests/test_arxiv_crawler.py tests/test_runtime_tracking.py tests/test_concurrent_crawler.py
python -m src.m1_crawling.run_arxiv_only --range 5 --workers 3 --batch-size 50 --preview
```

Trong Colab, chạy lại cell SET UP để `git pull` phiên bản mới (hoặc clone lại nếu đã đổi thư mục). Sau đó mount Drive và giữ nguyên `RANGE_ID`, `BATCH_SIZE = 50`, `DATA_DIR` đã dùng. Thêm `MAX_WORKERS = 3` ở cell cấu hình. Không cần xóa checkpoint cũ.

### Fast Crawl

```python
fast_crawl(batches=10)  # tối đa 10 batch mới, mỗi batch 50 ID
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

- Đây là **concurrent xử lý bài/giải nén**, không phải nhiều HTTP request đồng thời. Không tăng số request mỗi giây; tốc độ có thể tăng ít nếu nút thắt là chờ arXiv.
- Chỉ một notebook/process ghi vào cùng `DATA_DIR` tại một thời điểm. Nếu dừng giữa batch, checkpoint cuối cùng đã hoàn thành vẫn còn; batch đang dở có thể phải chạy lại.
- Không đổi `BATCH_SIZE` trong cùng thư mục checkpoint; thay đổi `MAX_WORKERS` được.
- Test chạy offline, chưa đo tốc độ thực tế trên arXiv. Nên benchmark 1 vs 3 worker trên các nhóm ID tương đương và xem lỗi 429.
