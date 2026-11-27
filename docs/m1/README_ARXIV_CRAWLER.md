# M1: arXiv Crawler & Source Processing (nhóm 6)

> **Phạm vi của module này**: Tra ID, metadata, phiên bản và tải `.tex`/`.bib` (bao gồm mọi revision); xử lý lỗi; đóng gói dữ liệu thành batch, backup Drive. **Không gọi Semantic Scholar** và **không thay đổi cấu trúc chung** (`common/`, `corpus.py`, `pipeline.py`, `run_m1.py`). Thành viên khác tiếp nhận dữ liệu bằng hợp đồng ở phần 8.

Nguồn yêu cầu: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/

## 1. File thuộc trách nhiệm arXiv Crawler

| File | Vai trò |
|---|---|
| `discover.py` (**đã hiện thực**) | Tra 1 ID hoặc tối đa 100 ID/request, parse Atom, `PaperMeta`, số phiên bản |
| `download.py` (**đã hiện thực**) | Tải có giới hạn kích thước, nhận dạng tar/gzip/zip/TeX/PDF, extract an toàn `.tex`/`.bib` |
| `arxiv_http.py` (**mới**) | HTTP sessions riêng theo worker, **một kết nối hoạt động** và **bộ giới hạn >=3s dùng chung** cho API + source, retry 429/5xx/network |
| `assigned_ranges.py` (**mới**) | 5 khoảng ID, mỗi khoảng dự kiến 5000 ID; xử lý giao tháng |
| `run_arxiv_only.py` (**mới**) | CLI độc lập, chia batch, tạo corpus, backup Drive, tiếp tục sau ngắt |
| `requirements-crawler.txt` (**mới**) | Gói pip tối thiểu cho crawler |
| `summarize_backups.py` (**mới**) | Gộp `papers.jsonl` và `crawl_records.jsonl` từ các checkpoint để bàn giao |
| `tests/test_arxiv_crawler.py` (**mới**) | Test OFFLINE, không spam arXiv |

Vì các hàm trong `src/common/*.py`, `m1_crawling/corpus.py` và `pipeline.py` của skeleton vẫn là `NotImplementedError`, **chạy riêng** bằng `python -m src.m1_crawling.run_arxiv_only`. Không chạy `run_m1.py` lúc này. Sau khi các đồng đội viết xong, gọi `fetch_papers_by_ids`, `fetch_paper_by_id`, `list_versions`, `download_source_archive`, `extract_tex_and_bib` từ pipeline sẽ được.

## 2. Khoảng ID từ hình phân công — CẦN KIỂM TRA GIỚI HẠN 2 THÁNG

| STT | start | end | số ID (dự kiến) |
|--|--|--|--:|
|1|`2609.37834`|`2610.02470`|5000|
|2|`2604.15535`|`2604.20534`|5000|
|3|`2604.00535`|`2604.05534`|5000|
|4|`2603.26580`|`2604.00534`|5000|
|5|`2603.15580`|`2603.20579`|5000|

Ảnh **không ghi ID cuối tháng**. Vì 3 khoảng cùng tháng có 5000 ID, code **giả định** mỗi khoảng xuyên tháng cũng có đúng 5000 ID; từ đó tính ra `2603.31045` và `2609.40363` là ID cuối tháng. Đây là *suy luận*, KHÔNG phải số giảng viên xác nhận. Trước khi crawl toàn bộ phải xác minh qua `--verify-boundaries`, hoặc với bảng phân công/giảng viên. Lệnh kiểm tra truy vấn cặp ID cuối tháng và ngay sau đó, **báo lỗi và dừng** nếu giới hạn có vẻ sai. Một ID đơn lẻ không tồn tại chưa chứng minh tuyệt đối đó là cuối tháng, nên xác minh thêm nếu có bất thường.

```bash
python -m src.m1_crawling.run_arxiv_only --preview
python -m src.m1_crawling.run_arxiv_only --verify-boundaries --next 1 --range 4
```

Nếu kiểm tra báo sai, **KHÔNG tự chạy tiếp**. Điều chỉnh `cross_month_limit` trong `assigned_ranges.py` sau khi kiểm chứng và chạy lại preview. Mọi thay đổi khoảng ID cần thông báo nhóm.

## 3. Cài đặt (VS Code/Windows hoặc Colab)

Từ **thư mục gốc repository** (`arXir_project-main/`):

```bash
python -m pip install -r src/m1_crawling/requirements-crawler.txt
python -m pytest -q tests/test_arxiv_crawler.py
python -m src.m1_crawling.run_arxiv_only --preview
```

Python khuyến nghị **3.11 hoặc 3.12**. Ở Colab dùng runtime **CPU**. Đối với crawler thuần, `requests` là dependency HTTP chính; `psutil` đo RSS. Không cần cài toàn bộ M2/M3 (rất tốn thời gian) để chạy crawler.

**Test thử đúng 1 batch nhỏ trên máy hoặc Colab:**

```bash
python -m src.m1_crawling.run_arxiv_only --range 3 --batch-size 2 --next 1 \
  --backup-dir data/crawler_backups --output-root data/crawler_scratch
```

Trên PowerShell, gõ thành **một dòng** (ký tự `\` ở trên là continuation cho Linux). Lệnh trên truy vấn các ID đầu tiên của range 3, không phải toàn bộ.

> Nếu thay đổi `--batch-size`, số range hoặc thứ tự khoảng, đừng dùng lại thư mục backup cũ với cùng tên `batch_00000`. Tốt nhất giữ batch size cố định hoặc tạo thư mục backup mới. Có thể chạy riêng range `--range 1` ... `--range 5` nhưng phải dành **thư mục Drive riêng** cho mỗi range vì batch_00000 của các range khác nhau có thể trùng tên.

## 4. Hướng dẫn chạy Colab, lưu dữ liệu vào Drive

1. Push các file mã nguồn trong bản cập nhật này lên GitHub của **nhóm**. Dữ liệu đầu ra **không push** vào repo.
2. Mở https://colab.research.google.com/ → Runtime → Change runtime type → CPU.
3. Chạy từng cell dưới đây (thay `OWNER`, `REPO` bằng repo thật):

```python
!git clone https://github.com/OWNER/REPO.git
%cd REPO
!pip -q install -r src/m1_crawling/requirements-crawler.txt
!python -m pytest -q tests/test_arxiv_crawler.py
!python -m src.m1_crawling.run_arxiv_only --preview
```

4. Mount Google Drive. Tạo folder `arxiv-m1` trong **My Drive**, rồi share folder cho nhóm (hoặc dùng Shared Drive nếu có quyền):

```python
from google.colab import drive
drive.mount('/content/drive')
BACKUP = '/content/drive/MyDrive/arxiv-m1'
```

5. Lần chạy đầu nên kiểm tra ranh giới và thử 1 batch nhỏ:

```python
!python -m src.m1_crawling.run_arxiv_only --verify-boundaries --range 3 --next 1 --batch-size 50 --backup-dir '{BACKUP}/range3'
```

6. Nếu ổn, chạy 2 hoặc 5 batch/lần (mỗi batch 50 bài). **Tiếp tục bằng cách chạy lại chính lệnh đó**, crawler tự tìm các batch chưa có checkpoint hợp lệ:

```python
!python -m src.m1_crawling.run_arxiv_only --range 3 --next 5 --batch-size 50 --backup-dir '{BACKUP}/range3'
```

Hoặc 5 khoảng, một thư mục chung, không lẫn với `range3`:

```python
!python -m src.m1_crawling.run_arxiv_only --range 0 --next 5 --batch-size 50 --backup-dir '{BACKUP}/all_ranges'
```

**Cảnh báo**: Không chạy đồng thời hai phiên Colab / máy trên cùng nhóm IP để rút thời gian request: arXiv yêu cầu một connection và tối thiểu 3s/request. Bản concurrent cho phép nhiều worker xử lý/extract bài nhưng khóa toàn bộ HTTP (kể cả tải stream), nên không tăng số kết nối hay tốc độ gửi request. Nếu thời gian giới hạn của Colab ngắt, mở phiên mới, clone lại repo, mount cùng Drive, rồi chạy lại cùng lệnh; batch đã xong sẽ được bỏ qua.

Nếu file `.json` của batch có `failed > 0`, sử dụng:

```python
!python -m src.m1_crawling.run_arxiv_only --range 3 --next 5 --batch-size 50 --retry-failed --backup-dir '{BACKUP}/range3'
```

`--retry-failed` khôi phục batch cũ và **chỉ làm lại paper lỗi**, không tải lại paper đã thành công. Lưu ý nếu một paper có nhiều phiên bản, khi paper đó lỗi thì code hiện tại tải lại các phiên bản của **paper đó**. Các paper khác trong batch vẫn được giữ. Khi đã hết lỗi, kiểm tra SHA256 của checkpoint:

```python
!python -m src.m1_crawling.run_arxiv_only --range 3 --next 0 --check-backups --batch-size 50 --backup-dir '{BACKUP}/range3'
```

`--check-backups` có thể tốn I/O vì đọc toàn bộ file nén; chỉ dùng lúc cần kiểm tra tính toàn vẹn.

## 5. Tối ưu hiệu năng, lý do vẫn có thể lâu

- **Metadata batched**: 50 ID trong **một** API query thay vì một query cho mỗi ID; không tải PDF, không qua trang HTML, không dùng Selenium.
- **Một kết nối HTTP tại một thời điểm** chung metadata + source, interval mặc định `3.1s` trên toàn bộ worker, retry với exponential backoff/Retry-After. Dùng `--workers 1..4` (mặc định 1) để chồng lấp xử lý file; không tăng số kết nối hay request/giây.
- **Download streaming** 256 KiB, không giữ archive lớn trong RAM; extraction theo từng member, chỉ `.tex`, `.bib`, cấm path traversal/symlink. Nếu archive quá lớn hoặc lạ thì ghi lỗi, không ghi nhầm là PDF-only.
- **Một số paper có nhiều phiên bản** ⇒ phải tải v1..vN. Với ~25.000 paper và tối thiểu một download/paper: ~75.000s (~20h50m) chỉ dành cho pacing source. Mạng, retry, versions, nén/backup có thể tăng thời gian, không thể cam kết dưới 20h khi tuân thủ điều khoản API.
- **Sao lưu theo batch**: mỗi 50 paper sau khi crawl được đóng gói thành một `.tar.gz` và manifest `.json` trên Drive; scratch Colab được dọn để tiết kiệm dung lượng.
- **Crawl mỗi batch có thể chứa lỗi**; xem `failed` trong manifest; không được coi error là 404 hay PDF-only.

## 6. Đầu ra và tên các biến

Ví dụ trong Drive:

```text
arxiv-m1/range3/
├── batch_00000.tar.gz
├── batch_00000.json
├── batch_00001.tar.gz
├── batch_00001.json
└── ...
```

Mỗi `batch_*.tar.gz` chứa:

```text
working/2604-00535/
  paper.json                # metadata, abstract, raw, latest_version
  status.json               # status tổng của publication
  v1/
    metadata.json           # ID phiên bản + ngày version nếu xác minh được
    status.json             # tình trạng tải, số bytes, số file, thời gian
    sources/main.tex        # bản gốc, bytes không bị sửa
    sources/subdir/refs.bib # chỉ giữ .tex / .bib, nguyên đường dẫn tương đối
  v2/
    sources/...
  v3/
    empty.json              # bản không có TeX (nếu có)
crawl_records.jsonl         # 1 object / assigned ID (kể cả không tồn tại)
papers.jsonl                # 1 object / bài báo tìm được (không có version suffix)
metrics.json                # thống kê batch
```

**`paper.json`** dùng dataclass `PaperMeta`:

| Field | Kiểu/ý nghĩa |
|---|---|
| `arxiv_id` | `str`, canonical `2604.00535`, **không chứa `vN`** |
| `title` | `str`, tên bài báo |
| `authors` | `list[str]`, tên tác giả |
| `abstract` | `str`, nội dung tóm tắt |
| `latest_version` | `int`, n phiên bản, dùng `range(1,n+1)` |
| `submission_date` | `str`, ngày lần đầu, ISO `YYYY-MM-DD` |
| `revised_dates` | `list[str]`, các ngày revision biết được; nếu `latest_version>2`, có thể thiếu ngày giữa khi API không cho kết quả |
| `venue` | `str` hoặc `null`, từ journal_ref |
| `categories` | `list[str]`, category tags |
| `raw.atom_updated` | `str`, ngày Atom updated gần nhất |
| `raw.revision_dates_complete` | `bool`, **true** nếu các ngày sửa được xác nhận đầy đủ bằng API (không được đoán) |

**`status.json` publication**: `arxiv_id`, `status`, `versions` (`list[dict]`), `error`, `elapsed_sec`.

`status` ở publication và version:

| Status | Ý nghĩa / hành động |
|---|---|
| `ok` | Đã thu được ít nhất một `.tex`/`.bib` |
| `no_tex` | Không có source LaTeX: PDF-only, empty archive, thiếu tex/bib hoặc HTTP 404/410 (xem `reason`) |
| `not_found` | API tìm ID nhưng không thấy (vẫn tạo `working/<id>/status.json`) |
| `error` | Lỗi mạng, lỗi archive, quá dung lượng, lỗi không xác định; cần retry |

`vN/metadata.json`: `arxiv_id`, `version`, `versioned_id`, `updated_date` (có thể `null` nếu API không cho), `date_source`, `title_latest`, `authors_latest`, `title_authors_scope`. **Không** gán tiêu đề/tác giả mới nhất thành metadata lịch sử được xác minh của từng version.

`vN/status.json`: `version`, `status`, `archive_kind`, `archive_bytes`, `filtered_bytes`, `file_count`, `files`, `reason`, `elapsed_sec`.

`metrics.json` và manifest của batch: `requested`, `processed_this_run`, `ok`, `no_tex`, `not_found`, `failed`, `api_requests_this_run`, `api_retries_this_run`, `discovery_seconds_this_run`, `runtime_seconds_this_run`, `input_archive_bytes`, `filtered_source_bytes`, `work_dir_bytes_before_packaging`, `peak_rss_bytes`, `average_rss_bytes`, `rss_samples`, `sampled_peak_scratch_bytes`. RAM và disk được lấy mẫu nên chỉ là ước lượng, không phải mức đỉnh toán học tuyệt đối. Manifest trên Drive thêm `archive_bytes`, `archive_sha256`, `archive_seconds`.

Lưu ý: đây là **chỉ số riêng module arXiv**, không phải benchmark M1 toàn hệ thống (M1 còn Semantic Scholar và tạo bảng). Benchmark cuối theo đề: chạy hệ thống đầy đủ trên Colab CPU-only; đo tổng wall time, RAM trung bình / peak, disk peak. Người phụ trách pipeline cần instrument các metric đó. Nếu không thể giữ cả 25.000 bài cùng Colab session, cần ghi rõ phương pháp benchmark mẫu và giới hạn trong báo cáo, **không tự nhận là đã benchmark toàn bộ**.

### Gộp metadata cho người phụ trách Data Management

Sau khi crawl xong các batch của một range, chạy ngay trong Colab:

```python
!python -m src.m1_crawling.summarize_backups --backup-dir '{BACKUP}/range3' --output-dir '{BACKUP}/range3/summary'
```

Lệnh tạo `summary/papers.jsonl`, `summary/crawl_records.jsonl`, `summary/summary.json` để đồng đội đọc **không cần giải nén hàng loạt source TeX**. Đừng đặt `--backup-dir` và `--output-dir` trùng nhau. Có thể chạy lại khi số batch tăng; file summary được tạo lại, không nhân đôi các hàng. Dữ liệu `.tex/.bib` vẫn nằm trong archive của từng batch.

## 7. Giao diện hàm (cho thành viên tích hợp)

```python
from src.m1_crawling.arxiv_http import ArxivHTTP
from src.m1_crawling.discover import fetch_papers_by_ids, list_versions
from src.m1_crawling.download import download_source_archive, extract_tex_and_bib
from pathlib import Path

with ArxivHTTP(delay=3.1) as client:   # SHARE ONE THROTTLED CLIENT!
    paper_map = fetch_papers_by_ids(["2604.00535", "2604.00536"], http=client)
    for paper_id, metadata in paper_map.items():
        for version in list_versions(metadata):
            path = download_source_archive(paper_id, version, Path("temp/source.bin"), http=client)
            files = extract_tex_and_bib(path, Path("temp/extracted"))
            # Save via group's corpus.py; then delete temporary archive.
```

Các chữ ký cũ của `fetch_paper_by_id`, `list_versions`, `source_url`, `download_source_archive`, `detect_archive_kind`, `extract_tex_and_bib`, `cleanup_temp_archive` **vẫn giữ nguyên** (chỉ thêm optional args). `fetch_papers_by_ids` là hàm mới để tăng hiệu năng. Nếu gọi riêng từng hàm tạo HTTP client riêng, tốc độ sẽ chậm và **không có cùng rate limiter**; pipeline nên tạo một ArxivHTTP xuyên suốt.

## 8. Cách đồng đội nhận dữ liệu (không cần hỏi lại tên biến)

- Người phụ trách Data Management lấy `papers.jsonl` và `crawl_records.jsonl` từ mỗi batch. `papers.jsonl` đã có đúng 6 trường schema `PaperRow`: `arxiv_id`, `title`, `authors`, `submission_date`, `revised_dates`, `venue`.
- `working/{arxiv_id.replace('.', '-')}/vN/sources/` chứa TeX/BibTeX để M2 đọc; **KHÔNG** sửa nội dung/đổi relative path của `.tex`/`.bib`.
- Không có nguồn: đọc `vN/empty.json`; lỗi: đọc `vN/status.json`; ID không tồn tại: đọc `working/<id>/status.json`.
- Người phụ trách Semantic Scholar gọi **1 lần mỗi publication** theo `arxiv_id` và tạo `references_s2.json`; hiện **crawler không tạo `references` table** vì chưa có dữ liệu từ Semantic Scholar. Nên giữ toàn bộ S2 refs trong corpus như yêu cầu đề.
- Nếu muốn import batch: dùng `tarfile.open(..., 'r:gz')` trong Python với kiểm tra đường dẫn an toàn; lưu ra một thư mục working bền vững hoặc streaming từng file. Không nén lại nguồn gốc do crawler đã loại ảnh và giữ nguyên TeX.
- Có thể thực hiện ở máy Windows, Google Drive hay Colab (batch archives độc lập); `data/` nên nằm ngoài Git / trong `.gitignore`.

## 9. Kiểm chứng sau khi crawl

- [ ] Đã xác thực các ID cuối tháng 03 & 09, không dùng suy luận 5000 mù quáng.
- [ ] 5 khoảng không trùng nhau; `--preview` ra đúng **25.000 ID** dự kiến.
- [ ] Đã chạy offline unit tests thành công.
- [ ] Đã tải thử ~2-50 ID thật, kiểm tra `.tex` và `.bib` nguyên nội dung.
- [ ] Không có `*.partial` lưu trên Drive như bản hoàn chỉnh; với từng `.tar.gz` có `batch_*.json` hợp lệ.
- [ ] `failed=0`, hoặc có danh sách lỗi riêng và giải thích; tuyệt đối không ghi `error` thành `no_tex`.
- [ ] Metadata, `papers.jsonl`, batch manifest đủ để Data Management nhận.
- [ ] Xác nhận tổng số batch: 100 cho mỗi range, 500 cho cả 5 (nếu batch-size=50).
- [ ] Khôi phục một Colab session mới chỉ cần mount Drive + chạy lại cùng lệnh.
- [ ] Riêng báo cáo cuối: tích hợp Semantic Scholar và benchmark M1 đúng Colab CPU-only.

## 10. Những hạn chế minh bạch

1. Không có truy cập arXiv từ môi trường build offline hiện tại, nên **chưa xác minh bằng live HTTP** rằng các ID tháng 03/09 ở ranh giới tồn tại và chưa kiểm thử throughput thực trên Colab. `--verify-boundaries` là bước bắt buộc trước khi crawl thật.
2. Endpoint API có thể không trả đầy đủ intermediate revision dates. Metadata giữ `raw.revision_dates_complete` để nhóm bổ sung hoặc nêu hạn chế, thay vì bịa ngày.
3. Archive vượt giới hạn bảo vệ sẽ thành `error` (có thể tăng giới hạn trong `download.py` nếu Colab đủ dung lượng), không được lẳng lặng bỏ bài.
4. Batch là mức checkpoint. Nếu Colab ngắt **giữa một batch chưa hoàn thành**, tối đa số paper đang trong batch đó có thể cần chạy lại. Giảm `--batch-size` xuống 10-25 khi mạng không ổn định, nhưng tạo thư mục backup mới.
5. M1 thống kê RAM/disk cho toàn bộ hệ thống phải do pipeline hoàn chỉnh thực hiện, ngoài phần chỉ số crawler ở đây.


## Concurrent có giới hạn (cập nhật)

- `--workers 1` = chế độ tuần tự như trước; `--workers 3` = tối đa 3 bài được xử lý đồng thời trong **một batch**. Batch vẫn chạy tuần tự.
- Các worker có session riêng, nhưng toàn bộ kết nối HTTP (kể cả thời gian đọc stream) đi qua một khóa chung và khoảng cách request tối thiểu 3.1 giây; HTTP 429 áp dụng thời gian chờ chung.
- `--retry-failed` chỉ duyệt checkpoint cũ có `failed > 0`, không tạo batch mới. Thành công và `no_tex` vẫn giữ nguyên; chỉ retry phiên bản lỗi.
- Checkpoint cũ và `runtime_history.csv` tương thích. `metrics.csv` bổ sung cột `workers_this_run` cho batch mới/cập nhật.
- Benchmark nên so sánh 1 worker với 3 worker trên các tập ID tương đương; không cam kết tăng tốc đáng kể nếu nút thắt là HTTP.
- Chạy offline: `python -m pytest -q tests/test_arxiv_crawler.py tests/test_runtime_tracking.py tests/test_concurrent_crawler.py`.
