# M1 — Semantic Scholar references + 2 bảng papers/references (cách chạy)

> **Đây là "phần của người 2"**: crawl references qua Semantic Scholar, xuất 2 bảng
> `papers` / `references` + validate, và pipeline M1 đầy đủ.
> Crawler arXiv (tải source `.tex`/`.bib` hàng loạt) là phần của người 1 —
> xem [`README_ARXIV_CRAWLER.md`](README_ARXIV_CRAWLER.md) và [`README_CONCURRENT_VI.md`](README_CONCURRENT_VI.md).

Nguồn yêu cầu: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/>

## 1. File thuộc trách nhiệm phần này

| File | Vai trò |
|---|---|
| `semantic_scholar.py` | Gọi S2 Graph API lấy references của 1 publication; chuẩn hóa record local |
| `tables.py` | Xuất `papers.json` + `references.json` (cột phẳng); `validate_m1_tables` |
| `pipeline.py` | Nối tất cả: discover → download mọi version → S2 → tables + metrics |
| `run_m1.py` | CLI end-to-end: `--ids`, `--semantic-scholar-api-key`, `--output` |
| `corpus.py` | Ghi working folder (`paper.json`, `vN/sources/`, `references_s2.json`) |
| `analyze.py` | Số liệu corpus (success rate, kích thước, ref coverage) → `metrics_m1.json` |
| `src/common/{ids,io,metrics,rate_limit}.py` | Helpers dùng chung (normalize ID, JSONL/JSON, track_run, retry/delay) |
| `colab_s2_references.ipynb` | Notebook Colab production: đọc checkpoint người 1 → crawl S2 (resume) → xuất bảng |
| `tests/test_m1_pipeline.py` | Test OFFLINE (mock network), không gọi arXiv / S2 thật |

Phần này **không** đổi CLI crawler `run_arxiv_only.py` của người 1.

## 2. Tiền đề

1. Người 1 đã crawl (hoặc đang crawl) và có checkpoint `batch_*.tar.gz` + `batch_*.json`
   trên Google Drive cho range của bạn.
2. Code trên nhánh của nhóm (hiện tại `M1-update`) đã được push; notebook sẽ `git pull` nhánh đó.
3. (Khuyến nghị) API key Semantic Scholar — không có vẫn chạy được nhưng dễ 429 hơn.

```text
Unauthenticated S2: ~1 request/s và 100 request / 5 phút.
Có key: ổn định hơn. Key đặt trong env S2_API_KEY hoặc Secrets của Colab.
```

## 3. Cài đặt & test offline (máy Windows / VS Code)

Từ thư mục gốc repository:

```bash
python -m pip install -r src/requirements.txt
python -m pytest -q tests/test_m1_pipeline.py
```

Test mock toàn bộ network (S2, table write, pipeline end-to-end) — không spam API.
Nếu chạy crawler người 1 trên máy thì cài `requirements-crawler.txt`; phần này cần
đầy đủ `src/requirements.txt` (arxiv, requests, psutil, pandas…).

## 4. Cách chạy A — Colab trên checkpoint Drive của người 1 (production)

Notebook: `src/m1_crawling/colab_s2_references.ipynb`. Chạy **sau** notebook crawl
`M1_Colab_Concurrent_Limited.ipynb` / `colab_shared_crawler.ipynb` của người 1.
Quy trình: GitHub branch → Drive → đọc ID từ checkpoint → crawl references (resume)
→ xuất 2 bảng + validate.

### 4.1. SET UP — clone branch và cài thư viện

- Cell SET UP đầu tiên clone nhánh `BRANCH` (mặc định `M1-update`) từ `REPO_URL` của nhóm.
  Nếu đã clone rồi thì `fetch` + `checkout` + `pull --ff-only`.
- Cài `src/requirements.txt`, rồi chạy `pytest tests/test_m1_pipeline.py` ngay trong Colab
  để chắc code khớp nhánh mới nhất.

### 4.2. Mount Google Drive

```python
from google.colab import drive
drive.mount("/content/drive")
```

### 4.3. Trỏ đúng thư mục Drive của range

`RANGE_ID` và `DATA_DIR` phải **trùng với notebook crawl của người 1** để tìm được checkpoint:

```python
RANGE_ID = 5             # range của người chạy (1..5)
DATA_DIR = Path(f"/content/drive/MyDrive/arxiv-project-data/m1/range_{RANGE_ID}_dev")
```

Cell assert sẽ báo lỗi nếu chưa có `batch_*.json` — tức là phải chạy crawl người 1 trước.
Dữ liệu của phần này ghi **xen vào cạnh** checkpoint, không đụng file người 1:

```text
DATA_DIR/
  batch_00000.tar.gz + .json          # checkpoint của người 1 (nguyên trạng)
  references/<folder>/references_s2.json   # MỌI ref đã crawl (resume tại đây)
  tables/papers.json
  tables/references.json
  tables/metrics_s2_references.json
  tables/s2_crawl_records.csv
```

### 4.4. Nạp S2_API_KEY

Đặt env `S2_API_KEY` trong notebook (hoặc add secret của Colab rồi đọc vào env).
**Không commit key vào repo** — nếu key đã lỡ nằm trong notebook thì xoá cell
hardcode, rotate key trên S2, và chỉ giữ env/Secrets.

### 4.5. Đọc danh sách paper từ checkpoint

Mỗi `batch_*.tar.gz` chứa `papers.jsonl` (metadata người 1 đã crawl). Cell loader:

- giải nén `papers.jsonl` + `crawl_records.jsonl` từ từng archive;
- chỉ giữ paper có `status == "ok"` trong `crawl_records.jsonl` (paper lỗi không có metadata để tra cứu);
- dedupe theo `arxiv_id`.

Notebook đọc API key từ biến môi trường `S2_API_KEY`; không đặt key trực tiếp
trong notebook. Luồng request dùng chung bộ pacing/cooldown của
`semantic_scholar.py`, bao gồm cả các lần retry.

### 4.6. Crawl references (resume, có đo runtime)

Mỗi paper: `fetch_s2_references` → `s2_ref_to_local_record` → ghi
`DATA_DIR/references/<folder>/references_s2.json`.

- **1 request / publication** (S2 không phân version), delay ≥ 1s do `S2_MIN_DELAY_SEC` trong library lo.
- **Resume**: paper đã có `references_s2.json` → `skipped`, không gọi API lại. Run bị ngắt
  thì mở lại session, mount Drive, chạy lại cell là tiếp tục.
- Lỗi từng paper (chưa index 404, 429 sau retry, mất mạng) được log rồi bỏ qua, không dừng cả run.
- Progress in mỗi 50 paper; cuối run in số `ok` / `skipped` / `error`, tổng refs, wall-clock, peak RAM.
- Phản hồi HTTP 200 chỉ được ghi cache khi payload có trường `references` kiểu
  list. `references: []` là kết quả `ok` hợp lệ; thiếu trường hoặc sai kiểu là
  `failed`. Phần tử reference không phải object cũng được ghi nhận là lỗi và
  không ghi cache để tránh mất dữ liệu âm thầm.

### 4.7. Recovery

Chỉ chạy lại cell crawl ở mục 4.6 là đủ: paper đã lưu sẽ `skipped`, paper lỗi/chưa tới được thử lại.
Nếu 429 dồn dập thì chờ ≥ 5 phút rồi chạy lại; **không tăng tốc hoặc mở 2 notebook song song**
trên cùng `DATA_DIR`.

### 4.8. Xuất 2 bảng `papers` / `references` + validate

- `papers`: metadata đọc từ checkpoint (1 hàng / publication, cột schema `PaperRow`).
- `references`: chỉ ref **có arXiv ID** (matching pool của M3); mọi ref vẫn nằm trong
  `references/<folder>/references_s2.json`.
- `validate_m1_tables` kiểm tra thiếu thông tin / sai kiểu / trùng lặp, in ra và ghi vào metrics.
- Ghi thêm `s2_crawl_records.csv` (log từng paper: arxiv_id, status, n_refs, n_arxiv, error)
  để đối chiếu / gửi người xử lý dữ liệu.

### 4.9. Bàn giao

Gửi cho người xử lý dữ liệu / đẩy lên Hugging Face ở M3:

- `tables/papers.json`, `tables/references.json`, `tables/s2_crawl_records.csv`;
- thư mục `references/` trên Drive (chứa **mọi** ref, kể cả ref không có arXiv ID) —
  đừng xóa trước khi submit M3.

## 5. Cách chạy B — pipeline đầy đủ trên máy (end-to-end)

Chạy được cả discover + download source + S2 references + tables trong **một lệnh**
(khi muốn benchmark M1 đầy đủ hoặc test nhỏ trên máy):

```bash
# env S2_API_KEY=xxx (Windows PowerShell: $env:S2_API_KEY="xxx")
python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
```

Tùy chọn:

| Flag | Ý nghĩa |
|---|---|
| `--ids` (bắt buộc) | File UTF-8, 1 arXiv ID / dòng (xem `assigned_ids.example.txt`) |
| `--semantic-scholar-api-key` | Key S2; fallback env `S2_API_KEY` |
| `--output` | Working corpus dir (mặc định `data/working`) |
| `--verbose` | DEBUG logging |

Pipeline tôn trọng `ARXIV_MIN_DELAY_SEC` (3s) và `S2_MIN_DELAY_SEC` (1s), một connection
tại một thời điểm. **1 paper lỗi thì log rồi tiếp tục**, không abort cả list.

Output trên đĩa:

```text
data/working/{2310-12345}/
  paper.json
  references_s2.json          # MỌI ref (kể cả không có arXiv ID)
  v1/sources/*.tex, *.bib
  v2/empty.json               # ví dụ PDF-only
data/tables/papers.json
data/tables/references.json   # CHỈ ref có arXiv ID
data/tables/metrics_m1.json   # time + RAM + n_refs + validation
```

## 6. Ràng buộc / lưu ý

- Bảng `references` CHỈ giữ ref có arXiv ID; local corpus PHẢI giữ đủ mọi ref.
- Ref không có arXiv ID → `ref_arxiv_id = null` ở local, bị loại khi xuất bảng.
- Scheme cũ `hep-th/9901001` được giữ nguyên, không đổi sang dạng mới.
- Không chạy 2 process/notebook cùng ghi vào một `DATA_DIR` / `TABLES_DIR`.
- Không commit `data/`, checkpoint Drive, hay API key.
- Benchmark cuối của đề là M1 **toàn hệ thống** trên Colab CPU-only (gộp phần người 1);
  số liệu trong notebook này là metric riêng phần S2 references.

## 7. Checklist "xong khi nào"

- [ ] `pytest tests/test_m1_pipeline.py` pass trên nhánh mới nhất.
- [ ] Notebook đọc được checkpoint của người 1 (đúng range / `DATA_DIR`).
- [ ] Mỗi paper `status=ok` trong checkpoint có `references/<folder>/references_s2.json`
      (hoặc đã được log là chưa index / lỗi có lý do).
- [ ] `papers.json` 1 hàng / paper; `references.json` chỉ ref có arXiv ID.
- [ ] `validate_m1_tables` ra `ok = True` (hoặc đã giải thích mọi issue trong metrics).
- [ ] `s2_crawl_records.csv` đủ để đối chiếu `ok` / `skipped` / `error`.
- [ ] Bàn giao `papers.json`, `references.json`, `references/` cho người xử lý dữ liệu.
- [ ] Không còn API key nào bị commit vào repo.
