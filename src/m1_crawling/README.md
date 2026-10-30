# Milestone 1 — Data Crawling

**Người làm M1 đọc file này trước khi mở code.**

Đề đầy đủ: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling>

## Bạn đang làm gì?

Lab Instructors giao một **danh sách arXiv ID**. Bạn phải:

1. Tra từng ID → metadata + **số version** (`v1` … `vN`).
2. Tải **source từng version** từ mirror export.
3. Chỉ giữ file `.tex` và `.bib` (bỏ figure binary bằng cách **không extract**, không sửa lệnh `\includegraphics` trong TeX).
4. Version không có TeX (PDF-only, docx, …): **giữ paper**, ghi **empty record**, không xóa publication.
5. Gọi Semantic Scholar lấy **mọi reference** của paper; lưu local hết; bảng Hugging Face `references` chỉ giữ reference **có arXiv ID**.

Không harvest cả arXiv. OAI-PMH / Kaggle chỉ là toolbox tùy chọn cho report.

Phụ thuộc: xong `src/common` (xem `src/common/README.md`).

Chạy (sau khi đã code):

```bash
python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
```

---

## Thứ tự nên code

```text
ids.py (common) → rate_limit + io
    → discover.py          (biết paper có mấy version)
    → download.py          (tải + extract)
    → semantic_scholar.py  (references)
    → corpus.py            (ghi folder)
    → tables.py            (2 bảng HF)
    → pipeline.py          (nối tất cả)
    → run_m1.py            (CLI)
    → analyze.py           (số liệu report)
```

Gọi `raise NotImplementedError` hiện tại = chỗ bạn **xóa và viết thân hàm**. Đừng đổi chữ ký hàm.

---

## Output trên đĩa (gợi ý đề)

```text
data/working/2310-12345/
  paper.json              # title, authors, submission_date, revised_dates, venue, versions
  references.json         # MỌI ref đã crawl (kể cả không có arXiv ID)
  v1/sources/*.tex, *.bib
  v2/sources/...
  v3/empty.json           # ví dụ PDF-only: {"empty": true, "reason": "pdf"}
data/tables/papers.jsonl
data/tables/references.jsonl   # CHỈ ref có arXiv ID
data/tables/metrics_m1.json
```

Tên folder: `2310.12345` → `2310-12345` (`folder_name_for_arxiv_id`).

---

## Từng file / từng hàm

### `discover.py` — tìm paper và đếm version

Dùng thư viện `arxiv` **≥ 4.0**: `arxiv.Client().results(arxiv.Search(...))`.
**Cấm** `search.results()` và `Result.download_source()` (đã bị gỡ).

| Hàm | Code cái gì | Trả về |
| --- | --- | --- |
| `fetch_paper_by_id` | `Search(id_list=[id])`. `paper.id` kiểu `.../abs/2310.12345v4` → `latest_version=4`. `published` → `submission_date`. Paper không tồn tại → **raise**, pipeline log fail. Delay ≥ 3s. | `PaperMeta` |
| `list_versions` | `latest=4` → `[1,2,3,4]`; submit 1 lần → `[1]` | `list[int]` |
| `harvest_oai_pmh_optional` | **Không bắt buộc.** Endpoint mới `https://oaipmh.arxiv.org/oai` (cũ đã retire). | list metadata |
| `load_kaggle_metadata_optional` | **Không bắt buộc.** JSONL Kaggle, không thay bước resolve ID được chấm. | DataFrame |

### `download.py` — tải source

URL: `https://export.arxiv.org/src/{id}vN`  
**Không** tải từ `arxiv.org` (dễ 403). User-Agent mô tả + delay 3s.

| Hàm | Code cái gì |
| --- | --- |
| `source_url` | Ghép `ARXIV_SRC_MIRROR` + `versioned_id` |
| `download_source_archive` | Tải **bytes archive** về file tạm (chưa giải nén). `urllib` hoặc `requests`. |
| `detect_archive_kind` | tar.gz / gzip tex / PDF / unknown — magic bytes hoặc content-type |
| `extract_tex_and_bib` | Chỉ file kết thúc `.tex` / `.bib` (không phân biệt hoa thường). Giữ relative path (paper nhiều file). **Không sửa nội dung TeX.** Không có tex/bib → `[]`. |
| `cleanup_temp_archive` | Xóa file tạm sau extract |

### `semantic_scholar.py` — reference metadata

Endpoint: `https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}`  
Fields **phẳng** (không `authors.name`): xem `S2_FIELDS` trong config.  
Header `x-api-key` nếu có `S2_API_KEY`. Delay ≥ 1s. Paper chưa index → `[]` + warning.

| Hàm | Code cái gì |
| --- | --- |
| `fetch_s2_references` | GET + parse `references` |
| `extract_arxiv_id_from_external_ids` | Lấy key `ArXiv`. Giữ nguyên `hep-th/9901001`. Không có → `None` |
| `s2_ref_to_local_record` | Record local: title, authors (list tên), date, `ref_arxiv_id` (nullable), `paperId` → `ref_s2_id` |

Gọi **một lần / publication** (S2 không phân version).

### `corpus.py` — ghi working folder

| Hàm | Code cái gì |
| --- | --- |
| `publication_dir` / `version_source_dir` | Path theo config + folder name |
| `save_paper_meta` | `paper.json` |
| `save_version_sources` | `empty=True` → marker, **không** xóa publication; `False` → copy tex/bib |
| `save_references` | `references.json` |
| `iter_publications` | Liệt kê paper đã crawl (M2 dùng) |

### `tables.py` — 2 bảng nộp cuối (M3 mới đẩy lên Hugging Face)

| Hàm | Code cái gì |
| --- | --- |
| `paper_meta_to_row` | 1 hàng / **publication** (không / version). `arxiv_id` **không** kèm `vN`. |
| `s2_records_to_reference_rows` | Bỏ ref thiếu ArXiv ID |
| `write_m1_tables` | `papers.jsonl` + `references.jsonl` |

Cột `papers`: `arxiv_id`, `title`, `authors`, `submission_date`, `revised_dates`, `venue`  
Cột `references`: `arxiv_id` (citing), `ref_arxiv_id`, `ref_title`, `ref_authors`, `ref_submission_date`, `ref_s2_id`

### `pipeline.py` — não M1

| Hàm | Thứ tự bên trong |
| --- | --- |
| `crawl_one_publication` | 1. fetch + list_versions → 2. save meta → 3. mỗi version: download, detect, extract hoặc empty, xóa archive → 4. S2 → 5. return tóm tắt |
| `run_milestone1` | `load_assigned_ids` → `track_run('m1')` vòng lặp; **1 paper lỗi thì log rồi tiếp**, không abort cả list; ghi tables + metrics |

Một connection tại một thời điểm (đề API etiquette).

### `run_m1.py`

`--ids`, `--semantic-scholar-api-key` (hoặc env `S2_API_KEY`), `--output` optional. `main` gọi `run_milestone1`.

### `analyze.py` — số cho Jupyter Book (repo report khác)

Đếm: paper thành công, success rate, size archive vs tex/bib (trước/sau bỏ figure), số ref trung bình, coverage S2, time / paper, peak/avg RAM, disk.

---

## Việc **không** làm ở M1

- Không parse cây LaTeX, không matching ML (M2/M3).
- Không sửa TeX để “xóa figure”.
- Không commit `data/` hay `assigned_ids.txt`.
- Report Jupyter Book = **repo GitHub Pages riêng**, không nhét vào đây.

## Xong M1 khi nào?

- [ ] Mọi ID trong `assigned_ids.txt` có folder; mọi `v1..vN` được xử lý
- [ ] Version PDF-only vẫn còn paper + empty marker
- [ ] Folder chỉ còn `.tex`/`.bib` (+ json metadata)
- [ ] `papers.jsonl` 1 hàng / paper; `references.jsonl` chỉ ref có arXiv ID
- [ ] `references.json` vẫn chứa ref không có arXiv ID
- [ ] Có `metrics_m1.json` (time + RAM) để nhóm viết book
