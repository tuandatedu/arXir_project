# Luồng Colab M1 — crawl theo batch và lưu trên Google Drive

Notebook hiện dùng: `M1_CONCURRENT.ipynb`. Notebook gọi `run_arxiv_only.py` để crawl arXiv theo checkpoint, sau đó gọi Semantic Scholar để lấy references. Các batch được xử lý lần lượt; `MAX_WORKERS` chỉ điều khiển worker bên trong từng batch.

## Chuẩn bị

1. Đảm bảo notebook clone đúng repository và branch tại cell SET UP (`REPO_URL`, `BRANCH`).
2. Chọn runtime CPU-only trong Colab và chạy các cell setup.
3. Mount Google Drive.
4. Ở cell cấu hình, chọn `RANGE_ID` được giao, giữ nguyên `BATCH_SIZE` khi đã có checkpoint và kiểm tra `DATA_DIR`.
5. Có thể thêm secret `S2_API_KEY` trong Colab để giảm khả năng bị giới hạn Semantic Scholar. Nếu không có key, API công khai có thể trả 429.

Notebook dùng `assigned_ranges.py` để tạo ID cho range đã chọn; không cần `assigned_ids.txt` trong luồng này. Các range băng qua tháng cần xác minh `cross_month_limit` trước khi crawl đầy đủ.

## Chạy crawl và lấy reference

Chạy các cell định nghĩa hàm trước, rồi chạy cell 5. Lệnh mặc định là:

```python
crawl_batches(batches=0)
```

- `batches=0`: tiếp tục tất cả batch còn thiếu hoặc có lỗi discovery trong range đã chọn.
- `batches=1`: xử lý tối đa một batch còn thiếu; dùng để chạy thử.
- Mỗi batch được crawl, lấy reference từ Semantic Scholar, rồi lưu bảng riêng trước khi chuyển batch tiếp theo.
- Output của cell 5 đang được capture để tránh log dài. Cell có thể chạy lâu; theo dõi trạng thái thực thi của Colab và kiểm tra các file trên Drive.
- Checkpoint hoàn tất được giữ lại khi chạy lại. Reference có trạng thái lỗi sẽ được thử lại ở lần gọi sau.

Nếu cần recovery paper crawl lỗi, dùng cell Recovery sau khi các cell định nghĩa đã chạy:

```python
recovery_crawl(batches=10, retries=4, backup_before=False)
```

Recovery chỉ xử lý checkpoint đã có lỗi; không tạo batch mới. Tránh chạy hai notebook/process trên cùng `DATA_DIR` cùng lúc.

## Build và validate bảng tổng

Sau khi crawl và lấy reference xong, chạy cell 9. Cell này gộp dữ liệu từ các checkpoint hợp lệ thành hai bảng tổng, rồi validate thiếu thông tin, sai kiểu dữ liệu và trùng lặp:

- `DATA_DIR/tables/papers.json`
- `DATA_DIR/tables/references.json`
- `DATA_DIR/tables/build_report.json`
- `DATA_DIR/tables/validation_report.json`

Cell 5 tạo bảng JSON cho từng batch tại `reference_XXXXX/tables/`, nhưng không validate. Bảng `references.json` chỉ chứa references có arXiv ID hợp lệ. Các file reference riêng trong `reference_XXXXX/` giữ toàn bộ kết quả Semantic Scholar, kể cả mục không có arXiv ID.

Các file `.jsonl` bên trong `batch_XXXXX.tar.gz` là dữ liệu checkpoint đầu vào của crawler; chúng khác với bảng JSON được xuất trong thư mục `tables/`.

## Các file chính trên Drive

Trong `DATA_DIR`:

- `batch_XXXXX.json`: manifest gồm ID, trạng thái crawl và tóm tắt references.
- `batch_XXXXX.tar.gz`: metadata `papers.jsonl`, `crawl_records.jsonl`, metrics và source `.tex`/`.bib` đã lọc.
- `reference_XXXXX/{arxiv-id}.json`: toàn bộ references từ Semantic Scholar của từng paper.
- `reference_XXXXX/tables/`: bảng JSON riêng của batch.
- `tables/`: bảng JSON tổng, build report và validation report sau cell 9.
- `runtime_history.csv`: wall-clock của các lượt Fast Crawl/Recovery.
- `reports/`: báo cáo thống kê được tạo bởi hàm `export_report()` ở cell 8.
- `reports/performance_metrics.csv`: per-batch/per-phase CPU, RAM, elapsed time, discovery, and scratch/output disk measurements.

`performance_metrics.csv` records arXiv batches, Semantic Scholar, table builds, and validation. CPU/RSS sample the Colab process tree once per second; CPU can exceed 100% across cores. `runtime_history.csv` records arXiv command wall time. `summary.json` aggregates sequential stage times and reports final output bytes separately from the sampled scratch peak.

## Kiểm tra kết quả

- Xem `batch_XXXXX.json` để biết số paper thành công/lỗi và trạng thái reference.
- Xem `tables/validation_report.json` sau cell 9 để biết lỗi và cảnh báo của hai bảng tổng.
- Chạy `export_report()` ở cell 8 nếu cần tạo/cập nhật báo cáo crawler và runtime.

Official workflow: `M1_CONCURRENT.ipynb` cell 5 crawls arXiv, fetches references, and builds per-batch tables; cell 9 builds/validates combined tables; cell 8 exports reports. `run_m1_all.py` post-processes existing batch checkpoints and does not crawl arXiv. `run_m1.py` is the older per-paper pipeline and is not used by the batch notebook.
