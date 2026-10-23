# `src/common` — code dùng chung (làm trước M1/M2/M3)

Các hàm ở đây **không thuộc một milestone riêng**, nhưng M1–M3 đều gọi chúng.
Người nhận việc “hạ tầng / utils” nên code **hết folder này trước**.

Không đổi tên hàm, không đổi tên cột trong `schemas.py`.

Đề bài: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/>

---

## `config.py` — không cần code

Chỉ chứa hằng số (URL, delay 3 giây, đường dẫn `data/`). Import, đừng copy số lung tung.

## `schemas.py` — không cần code

6 bảng Hugging Face. Khi ghi file, map đúng field:

| Bảng | Ai tạo | Cột bắt buộc |
| --- | --- | --- |
| `papers` | M1 | `arxiv_id`, `title`, `authors`, `submission_date`, `revised_dates`, `venue` |
| `references` | M1 | `arxiv_id` (paper đang cite), `ref_arxiv_id`, `ref_title`, `ref_authors`, `ref_submission_date`, `ref_s2_id` |
| `elements` | M2 | `element_id`, `arxiv_id`, `kind`, `content` |
| `hierarchy` | M2 | `arxiv_id`, `version`, `element_id`, `parent_id` |
| `bibtex` | M2 | `arxiv_id`, `citation_key`, `entry_type`, `title`, `authors`, `year`, `doi`, `journal`, `url` |
| `predictions` | M3 | `arxiv_id`, `partition`, `citation_key`, `groundtruth_arxiv_id`, `cand_1`…`cand_5` |

Cột `authors` / `revised_dates` = `list[str]`. **Cấm** object lồng nhau hoặc nhét JSON string.

---

## `ids.py` — chuẩn hóa ID

| Hàm | Việc cần code | Ví dụ |
| --- | --- | --- |
| `normalize_arxiv_id` | Bỏ `arXiv:`, URL, khoảng trắng; **tách** `vN`; giữ scheme cũ `hep-th/9901001` | `https://arxiv.org/abs/2310.12345v4` → `2310.12345` |
| `parse_version_suffix` | Regex `v(\d+)$` | `2310.12345v4` → `4`; không có `v` → `None` |
| `folder_name_for_arxiv_id` | `.` → `-`; `/` → `_` | `2310.12345` → `2310-12345` |
| `versioned_id` | Ghép `vN` | (`2310.12345`, 2) → `2310.12345v2` |
| `element_id` | `{folder}#{discriminant}` | (`2310.12345`, `s1`) → `2310-12345#s1` |

## `rate_limit.py` — không spam API

| Hàm | Việc cần code |
| --- | --- |
| `sleep_until_allowed` | Nếu chưa đủ `min_interval_sec` thì `time.sleep` phần còn thiếu; trả timestamp mới |
| `request_with_retry` | `requests`; User-Agent từ config; 429 đọc `Retry-After`; 403 trên `arxiv.org` = **sai mirror**, log rồi dừng, đừng retry điên |

arXiv ≥ **3 giây** / request. Semantic Scholar ≥ **1 giây** (không key: thêm giới hạn 100 req / 5 phút).

## `io.py` — đọc/ghi file

| Hàm | Việc cần code |
| --- | --- |
| `load_assigned_ids` | Bỏ dòng trống và `#...`; gọi `normalize_arxiv_id`; unique, giữ thứ tự |
| `write_json` / `read_json` | UTF-8, `indent=2`, `mkdir` parent |
| `write_jsonl` / `read_jsonl` | Một JSON object / dòng |
| `write_parquet_shard` | pandas/pyarrow; list[str] = kiểu list; cột nullable đúng schema |
| `read_parquet_table` | Đọc mọi `*.parquet` trong thư mục |
| `dataclass_to_dict` | `dataclasses.asdict` |

**Không commit** thư mục `data/`.

## `metrics.py` — số liệu cho report Colab

| Hàm | Việc cần code |
| --- | --- |
| `track_run` | Context manager: đo wall time + sample RAM (psutil); yield dict metrics |
| `directory_size_bytes` | Tổng size thư mục (như `du -sb`) |
| `sample_rss_bytes` | RSS process hiện tại |

---

## Checklist xong `common`

- [ ] `normalize_arxiv_id("2310.12345v2") == "2310.12345"`
- [ ] Ghi/đọc jsonl không lỗi Unicode
- [ ] Sleep giữa 2 lần gọi ≥ delay cấu hình
