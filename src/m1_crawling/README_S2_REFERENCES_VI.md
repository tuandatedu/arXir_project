# M1 — Semantic Scholar references + 2 bảng papers/references (cách chạy)

> **Đây là "phần của người 2"**: crawl references qua Semantic Scholar, xuất 2 bảng
> `papers` / `references` + validate, và pipeline M1 đầy đủ.
> Crawler arXiv (tải source `.tex`/`.bib` hàng loạt) là phần của người 1 —
> xem [`README_ARXIV_CRAWLER.md`](README_ARXIV_CRAWLER.md) và [`README_CONCURRENT_VI.md`](README_CONCURRENT_VI.md).

Nguồn yêu cầu: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/>

## 1. File thuộc trách nhiệm phần này

| File | Vai trò |
|---|---|
| `semantic_scholar.py` | Gọi S2 Graph API lấy references của 1 publication; chuẩn hóa record local; pacing/cooldown + validate payload |
| `s2_batch.py` | Batch runner dùng chung cho notebook: resume cache, validate payload, tổng hợp metrics theo publication |
| `tables.py` | Xuất `papers.json` + `references.json` (cột phẳng); `validate_m1_tables` |
| `pipeline.py` | Nối tất cả: discover → download mọi version → S2 → tables + metrics |
| `run_m1.py` | CLI end-to-end: `--ids`, `--semantic-scholar-api-key`, `--output` |
| `corpus.py` | Ghi working folder (`paper.json`, `vN/sources/`, `references_s2.json`) |
| `analyze.py` | Số liệu corpus (success rate, kích thước, ref coverage) → `metrics_m1.json` |
| `src/common/{ids,io,metrics,rate_limit}.py` | Helpers dùng chung (normalize ID, JSONL/JSON, track_run, retry/delay) |
| `colab_s2_references.ipynb` | Notebook Colab production: đọc checkpoint người 1 → crawl S2 (resume) → xuất bảng |
| `tests/test_m1_pipeline.py` | Test OFFLINE (mock network), không gọi arXiv / S2 thật |
| `tests/test_m1_batch.py` | Test OFFLINE batch runner: payload rỗng/thiếu/sai kiểu, cache, resume, pacing |

Phần này **không** đổi CLI crawler `run_arxiv_only.py` của người 1.

## 2. Tiền đề

1. Người 1 đã crawl (hoặc đang crawl) và có checkpoint `batch_*.tar.gz` + `batch_*.json`
   trên Google Drive cho range của bạn.
2. Code trên nhánh của nhóm (mặc định `M1-Update-pipeline`) đã được push; notebook sẽ `git pull` nhánh đó.
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

Chạy riêng test payload và bộ điều tiết request:

```powershell
python -m pytest -q tests/test_m1_pipeline.py -k "payload_validation_and_pacing"
python -m pytest -q tests/test_m1_batch.py
```

Test này kiểm tra `references=[]` hợp lệ, payload thiếu/sai kiểu
`references`, và việc request đi qua bộ điều tiết trước mỗi attempt.
`test_m1_batch.py` kiểm tra thêm cache/resume, trạng thái `invalid_id`, và
việc payload lỗi không tạo cache thành công.

## 4. Cách chạy A — Colab trên checkpoint Drive của người 1 (production)

Notebook: `src/m1_crawling/colab_s2_references.ipynb`. Chạy **sau** notebook crawl
`M1_Colab_Concurrent_Limited.ipynb` / `colab_shared_crawler.ipynb` của người 1.
Quy trình: GitHub branch → Drive → đọc ID từ checkpoint → crawl references (resume)
→ xuất 2 bảng + validate.

### 4.1. SET UP — clone branch và cài thư viện

- Cell SET UP đầu tiên clone nhánh `BRANCH` (mặc định `M1-Update-pipeline`) từ `REPO_URL` của nhóm.
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
RANGE_ID = 4             # range của người chạy (1..5)
DATA_DIR = Path(f"/content/drive/MyDrive/arxiv-project-data/m1/range_{RANGE_ID}_dev")
```

Cell assert sẽ báo lỗi nếu chưa có `batch_*.json` — tức là phải chạy crawl người 1 trước.
Notebook **chỉ đọc** checkpoint của người 1; dữ liệu S2 ghi vào thư mục riêng
`MY_REFS_DIR = /content/drive/MyDrive/references/range_{RANGE_ID}`:

```text
DATA_DIR/                                # checkpoint người 1 (chỉ đọc)
  batch_00000.tar.gz + .json
MY_REFS_DIR/
  reference/2307-00001.json              # MỌI ref đã crawl (resume tại đây, tên phẳng)
  tables/papers.json
  tables/references.json
  tables/metrics_s2_references.json
  tables/s2_crawl_records.csv
  tables/validation_report.json
```

### 4.4. Nạp S2_API_KEY

Đặt env `S2_API_KEY` trong notebook (hoặc add secret của Colab rồi đọc vào env).
**Không commit key vào repo** — nếu key đã lỡ nằm trong notebook thì xoá cell
hardcode, rotate key trên S2, và chỉ giữ env/Secrets. Nếu key từng bị chia sẻ ngoài
phạm vi nhóm, thu hồi và tạo key mới trước khi gửi code/báo cáo.

### 4.5. Đọc danh sách paper từ checkpoint

Mỗi `batch_*.tar.gz` chứa `papers.jsonl` (metadata người 1 đã crawl). Cell loader:

- đọc `papers.jsonl` từ mọi `batch_*.tgz`/`batch_*.json` tìm thấy;
- giữ **mọi** paper có metadata, không lọc theo trạng thái tải TeX (bài chỉ có PDF vẫn là một hàng của bảng `papers`);
- dedupe theo `arxiv_id`; báo riêng số ID đề giao còn thiếu so với checkpoint.

Notebook đọc API key từ `S2_API_KEY` (env) hoặc Colab Secrets rồi truyền thẳng
`api_key=` vào batch runner; không đặt key trực tiếp trong notebook. Luồng request
dùng chung bộ pacing/cooldown của `semantic_scholar.py`, bao gồm cả các lần retry.

### 4.6. Crawl references (resume, có đo runtime)

Mỗi paper: `run_s2_batch` gọi `fetch_s2_payload_with_status` →
`s2_ref_to_local_record` → ghi `MY_REFS_DIR/reference/<folder>.json`.

- **1 request / publication** (S2 không phân version), delay/cooldown do
  `S2_MIN_DELAY_SEC` / `S2_429_COOLDOWN_SEC` trong library lo, áp dụng cho cả retry.
- **Resume**: paper đã có cache hợp lệ → `from_cache = true`, không gọi API lại.
  Run bị ngắt thì mở lại session, mount Drive, chạy lại cell là tiếp tục.
- Lỗi từng paper (`not_indexed` 404, `failed` sau retry, `invalid_id`) được log rồi
  bỏ qua, không dừng cả run.
- Progress in mỗi 50 paper; cuối run in số `n_zero_refs` / `n_api_errors` /
  `n_processing_errors` / `n_cache_hits`.
- Phản hồi HTTP 200 chỉ được ghi cache khi payload có trường `references` kiểu
  list. `references: []` là kết quả `ok` hợp lệ; thiếu trường hoặc sai kiểu là
  `failed`. Phần tử reference không phải object cũng được ghi nhận là lỗi và
  không ghi cache để tránh mất dữ liệu âm thầm.
- Cache không phải list các object bị coi là hỏng và được crawl lại.

### 4.7. Recovery

Chạy lại cell crawl ở mục 4.6 là đủ: paper đã lưu sẽ `from_cache`, paper lỗi/chưa tới được thử lại.
Cell Recovery có thêm bước rà cache rỗng: `find_empty_cache_ids()` liệt kê các file
`[]` (có thể hợp lệ hoặc do code cũ). Chỉ đưa các ID đã kiểm tra vào
`run_s2_batch(..., force_recrawl_ids=[...])`; không xóa toàn bộ cache.
Nếu 429 dồn dập thì chờ ≥ 5 phút rồi chạy lại; **không tăng tốc hoặc mở 2 notebook song song**
trên cùng `MY_REFS_DIR` / `TABLES_DIR`.

### 4.8. Xuất 2 bảng `papers` / `references` + validate

- `papers`: metadata đọc từ checkpoint (1 hàng / publication, cột schema `PaperRow`).
- `references`: chỉ ref **có arXiv ID** (matching pool của M3); mọi ref vẫn nằm trong
  `MY_REFS_DIR/reference/<folder>.json`.
- `validate_m1_tables` kiểm tra thiếu thông tin / sai kiểu / trùng lặp, in ra và ghi vào metrics.
- Ghi thêm `s2_crawl_records.csv` (log từng paper: arxiv_id, status, n_refs, n_arxiv,
  n_refs_without_arxiv, from_cache, elapsed_s, error_kind, error) để đối chiếu / gửi người xử lý dữ liệu.

### 4.9. Bàn giao

Gửi cho người xử lý dữ liệu / đẩy lên Hugging Face ở M3:

- `MY_REFS_DIR/tables/papers.json`, `MY_REFS_DIR/tables/references.json`,
  `MY_REFS_DIR/tables/s2_crawl_records.csv`, `metrics_s2_references.json`,
  `validation_report.json`;
- thư mục `MY_REFS_DIR/reference/` trên Drive (chứa **mọi** ref, kể cả ref không có arXiv ID) —
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
- Không chạy 2 process/notebook cùng ghi vào một `MY_REFS_DIR` / `TABLES_DIR`.
- Không commit `data/`, checkpoint Drive, hay API key.
- `success_rate_fresh = n_ok_fresh / n_attempted_fresh`. `not_indexed` vẫn là một
  trạng thái hợp lệ (S2 chưa index), **không phải lỗi API**; nếu cả 5 lượt fresh
  đều `not_indexed` thì tỷ lệ là `0.0` nhưng `n_api_errors` vẫn có thể bằng 0.
- `n_ok` gồm cả cache hit. Số paper không lấy từ cache (ví dụ 189) không phải số
  HTTP request và không so trực tiếp với số `n_ok_fresh` của một range khác.
- Chưa đo được nếu không có log thật: **peak disk**, **số retry**, **HTTP 429**,
  **thời gian crawl lịch sử**. Ghi "chưa có dữ liệu", không suy từ cache/output size.
- Benchmark cuối của đề là M1 **toàn hệ thống** trên Colab CPU-only (gộp phần người 1);
  số liệu trong notebook này là metric riêng phần S2 references. Cần nhóm chốt người
  điều phối benchmark chung; số của phần S2 không thay được wall time/peak RAM/peak disk
  của toàn M1 trên cùng cửa sổ đo.

## 7. Checklist "xong khi nào"

- [ ] `pytest tests/test_m1_pipeline.py` và `pytest tests/test_m1_batch.py` pass trên nhánh mới nhất.
- [ ] Notebook đọc được checkpoint của người 1 (đúng range / `DATA_DIR`).
- [ ] Mỗi paper trong `papers_meta` có `MY_REFS_DIR/reference/<folder>.json`
      (hoặc đã được log là `not_indexed` / `failed` / `invalid_id` có lý do).
- [ ] `papers.json` 1 hàng / paper; `references.json` chỉ ref có arXiv ID.
- [ ] `validate_m1_tables` ra `ok = True` (hoặc đã giải thích mọi issue trong metrics).
- [ ] `s2_crawl_records.csv` đủ để đối chiếu `from_cache` / `ok` / `failed` / `not_indexed` / `invalid_id`.
- [ ] Bàn giao `papers.json`, `references.json`, `MY_REFS_DIR/reference/` cho người xử lý dữ liệu.
- [ ] Không còn API key nào bị commit vào repo.
