# Milestone 3 — Reference Matching Pipeline

> **Hướng dẫn thực hiện M3 cho người 1:** Dữ liệu làm sạch + gắn nhãn + tạo đặc trưng
>
> **Kết quả bàn giao cho người 2:** Dataset Parquet sẵn sàng huấn luyện mô hình

---

## Quick Start

**Tóm gọn 6 nhiệm vụ M3:**

| # | Nhiệm vụ | Trạng thái | File chính |
|---|----------|-----------|-----------|
| 1 | Làm sạch data (bibtex + references) | ✅ DONE | `cleaning.py` |
| 2 | Gắn nhãn manual: ≥5 papers × ≥20 entries | ⏳ **MANUAL** | `manual_tool.py` |
| 3 | Gắn nhãn auto: ≥10% papers ngoài manual | ✅ DONE | `labelling.py` |
| 4 | Tạo 14 đặc trưng phân biệt | ✅ DONE | `features.py` |
| 5 | Sinh bảng dữ liệu cặp (BibTeX ↔ Reference) | ✅ DONE | `dataset.py` |
| 6 | Chia train/valid/test split | ✅ DONE | `split.py` |
| **Output** | **Parquet files + visualization** | ✅ READY | `prepare_dataset.py` |

**🔴 Chỉ có Task 2 cần bạn làm:** Mở CSV → Tick checkbox `is_verified=YES` → Code auto-fill → Done

---

## Cấu trúc thư mục (Colab)

```text
MyDrive/
├── references/
│   └── range_1/               # M1
│       ├── reference/         # *.json từng bài
│       └── tables/
│           ├── papers.json
│           └── references.json
├── M2/
│   └── range_1/               # M2
│       └── M2_range_1_tables.zip   # gồm bibtex.jsonl + elements.jsonl
└── M3_matching/
    └── range_1/               # Output M3
        ├── tables/
        │   ├── bibtex.json
        │   └── references.json
        ├── labels/
        │   ├── manual/        # *.csv (mẫu) + *.json (sau import)
        │   └── automatic/
        │       └── automatic.zip     # gộp nhãn auto
        │           └── *.json
        └── prepared_dataset/
            ├── dataset_pairs.parquet
            ├── train_pairs.parquet
            ├── valid_pairs.parquet
            ├── test_pairs.parquet
            └── poster_feature_distribution.png
```

- `elements.jsonl` **không nằm trong M3**: pipeline đọc trực tiếp bên trong ZIP `M2_range_*_tables.zip` để tính `cite_count` (notebook truyền `elements_zip=M2_ZIP`).
- `labels/automatic/automatic.zip`: gộp toàn bộ `labels/automatic/*.json`; pipeline tự tạo khi chạy (`zip_auto_labels=True` trong notebook, CLI `--zip-auto`). `load_labels` đọc cả file `.json` lẫn zip, file `.json` được ưu tiên.
- Chạy local: dùng cùng cấu trúc dưới `data/` (`data/tables/`, `data/labels/`, `data/prepared_dataset/`).

---

## 1. Làm Sạch Dữ Liệu (Data Cleaning)

**File:** `src/m3_matching/cleaning.py`

Chuẩn hóa dữ liệu BibTeX + References để tiền xử lý cho phần so khớp:

- **`normalize_title()`**: Giải mã LaTeX accent, loại bỏ lệnh LaTeX, chuyển thường
  - Input: `Schr\"{o}dinger` → Output: `schrodinger` (không lỗi dấu)
- **`normalize_authors()`**: Xử lý 2 dạng họ tên, giữ tiền tố họ (van, von, de)
  - Input: `"Vaswani, Ashish"` & `"Ashish Vaswani"` → Output: `vaswani, a` (uniform)
- **`normalize_year()`**: Nhận diện năm từ chuỗi/số, kiểm tra [1800-2100]
- **`normalize_doi()`**: Bỏ tiền tố `https://doi.org/`, chuẩn hóa chữ thường

✅ **Không sửa dữ liệu gốc** — tạo cột chuẩn hóa riêng `title_norm`, `authors_norm`, ...

---

## 2. Gắn Nhãn Thủ Công (Manual Labeling) ⏳ **YOUR TASK**

**File:** `src/m3_matching/manual_tool.py`

### Tiêu chí chọn papers:
- **BibTeX entries:** ≥ 20
- **References (arXiv ID):** ≥ 20
- **Coverage ratio:** references / BibTeX ≥ 10%

**Tại sao cần cân bằng:**
- Paper A: 600 BibTeX | 3 References → 0.5% coverage → ❌ LOẠI (khó match)
- Paper B: 310 BibTeX | 157 References → 50.6% coverage → ✅ CHỌN (tốt)

### Yêu cầu (theo đề bài cho 1 người):
- ≥5 papers × ≥20 entries/paper = ≥100 tổng
- Nhóm k người: ≥5k papers, ≥100k entries

### Workflow (3 bước):

**Step 1: Export CSV templates**
```powershell
# Chạy notebook (mục Gán nhãn thủ công → Export template) hoặc command:
python -m src.m3_matching.manual_tool --export-template 2310.12345
```
→ File: `labels/manual/2310.12345.csv` có cột:
- `citation_key`, `bib_title`, `bib_authors`, ... (read-only)
- `suggested_ref_arxiv_id` ← gợi ý tự động
- `suggested_score` ← độ tin cậy gợi ý
- **`is_verified`** ← **BẠN TÁC CÁC DÒNG HỢP LỆ** (YES/NO)
- `groundtruth_arxiv_id` ← để trống (code auto-fill)

**Step 2: Kiểm tra bằng mắt và tick `is_verified`**

Mở CSV, so **`bib_title`** (entry lấy từ PDF) với **`suggested_ref_title`** (reference ứng viên từ M1). `suggested_score` chỉ là gợi ý, **không dùng score để quyết định thay cho việc so tiêu đề**.

| Trường hợp | `is_verified` | `groundtruth_arxiv_id` | Kết quả khi import |
|-----------|---------------|------------------------|--------------------|
| `bib_title` và `suggested_ref_title` là **cùng một bài** | `YES` | để trống | Tự lấy `suggested_ref_arxiv_id` |
| Cùng bài nhưng muốn chỉ định reference khác | `YES` | điền `ref_arxiv_id` đúng | Dùng ID đã điền |
| Gợi ý sai, nhưng tìm được reference đúng trong `references.json` | `YES` | điền `ref_arxiv_id` đúng | Dùng ID đã điền |
| Entry **không có reference arXiv nào khớp** | `YES` | để trống | `groundtruth = null` (hàng all-negative) |
| Gợi ý sai / không chắc / chưa kiểm tra | `NO` | để trống | Bị bỏ qua, không vào dataset |

Quy tắc nhanh:
1. Tiêu đề trùng → `YES`; tiêu đề khác → `NO` (trừ khi tự tìm được ref đúng).
2. **Ưu tiên tick các dòng `suggested_score` ≥ 0.8 trước** cho nhanh đủ 20 entry; thiếu mới xét các dòng thấp hơn. Dù score cao vẫn phải kiểm tra tiêu đề; score ≤0.6 thường là gợi ý sai.
3. Mỗi entry tối đa **1** groundtruth. Hai entry khác nhau chỉ cùng groundtruth nếu cả hai thực sự cite cùng một bài.
4. Dòng `NO` là "chưa xác nhận", **không phải nhãn âm**; muốn có nhãn âm cho entry không khớp thì dùng `YES` + groundtruth trống.
5. Chỉ cần tick `YES` cho ≥20 entry/paper; các dòng còn lại để `NO` cũng được.

Ví dụ:
- `thebelt2022maximizing` — title trùng, score 0.80 → `YES`.
- `dobbelaere2021machine` — bib là "Machine learning in chemical engineering..." nhưng gợi ý `2201.10035` là "Maximizing information..." → `NO`.

⏱ **Thời gian:** ~1 giờ cho ~100 entries

### Step 3: Import CSV → JSON
```powershell
# Chạy notebook (mục Import CSV) hoặc command:
python -m src.m3_matching.manual_tool --import-csv labels/manual/2310.12345.csv
```
→ Code tự động:
- Đọc CSV
- Lọc dòng `is_verified=YES`
- **Auto-fill `groundtruth_arxiv_id = suggested_ref_arxiv_id`** ← nhãn thực
- Nếu cả `groundtruth_arxiv_id` lẫn `suggested_ref_arxiv_id` đều trống → lưu `null` (hàng all-negative)
- Lưu JSON: `labels/manual/2310.12345.json`

### Cách nhóm tổng hợp:
Mỗi người làm 5 bài, import kết quả → Code gộp tất cả → nhãn cuối cùng sẵn sàng

---

## 3. Gắn Nhãn Tự Động (Automatic Labeling)

**File:** `src/m3_matching/labelling.py`

✅ Đã triển khai

**Quy tắc heuristic (`auto_match_one`):**
1. **Exact DOI match:** Khớp DOI 100% → match
2. **Exact title match:** Tiêu đề sau chuẩn hóa trùng 100% → match
3. **Fuzzy match:** Title ~88% + có tác giả trùng + chênh lệch năm ≤1 → match
4. **Ambiguity check:** Nếu 2 ứng viên gần bằng nhau → bỏ qua (không match)

**Output:** JSON files tại `labels/automatic/{arxiv_id}.json` (+ `labels/automatic/automatic.zip` nếu bật zip)

**Coverage:** ≥10% papers ngoài manual pool (tối thiểu 2 papers/người)

---

## 4. Tạo 14 Đặc Trưng (Feature Engineering)

**File:** `src/m3_matching/features.py`

Với mỗi cặp (BibTeX entry, Reference), tính 14 features:

| # | Tên | Phạm vi | Ý tưởng |
|---|-----|--------|--------|
| 1-6 | Title features | 0.0-1.0 | Độ tương đồng tiêu đề: levenshtein, token_sort, token_set, jaccard, exact, len_diff_ratio |
| 7-9 | Author features | 0.0-1.0 | Tác giả: jaccard (tập họ), first_match (tác giả đầu), any_match (bất kỳ) |
| 10-12 | Year features | -1 to 99 | Năm: diff (chênh lệch), exact (trùng/khác), missing (thiếu) |
| 13 | DOI match | -1/0/1 | DOI: trùng (1) / khác (-1) / không có (0) |
| 14 | Cite count | 0.0-N | Tần suất citation trong văn bản bài báo |

**Lý do từng feature:** Dùng cho **Poster A2** (giải thích tại sao cần feature này)

---

## 5. Tạo Bảng Dữ Liệu Huấn Luyện (Dataset Generation)

**File:** `src/m3_matching/dataset.py`

→ Với mỗi paper:
1. Tạo tích Descartes: BibTeX entries × References
2. Loại bỏ reference trùng (dedup)
3. Tính 14 features cho từng cặp
4. Gán nhãn:
   - `label=1` nếu ref_arxiv_id == groundtruth_arxiv_id (positive)
   - `label=0` nếu khác hoặc groundtruth=None (negative)

**Output:** DataFrame Parquet với 14 + 6 cột = 20 cột:
```
[14 features] + [arxiv_id, partition, citation_key, ref_arxiv_id, groundtruth_arxiv_id, label]
```
Khi train chỉ dùng 14 features + `label`; bỏ các cột định danh/groundtruth để tránh leakage.

---

## 6. Chia Split (Train/Valid/Test)

**File:** `src/m3_matching/split.py`

**Quy tắc:**
- **Không bao giờ chia theo từng pair** (tránh data leakage)
- **Chia theo publication** (toàn bộ paper vào một set)

**Kích thước (cho 1 người, k=1):**
- **Test:** 1 paper manual + 1 paper auto
- **Valid:** 1 paper manual + 1 paper auto
- **Train:** Toàn bộ paper còn lại

**Cho nhóm k người:**
- **Test:** k paper manual + k paper auto
- **Valid:** k paper manual + k paper auto
- **Train:** Toàn bộ paper còn lại

---

## Chạy Full Pipeline

### 1. Chuẩn bị input

Cần 2 bảng tại `data/tables/` (trên Colab là `M3_matching/range_{RANGE_ID}/tables/`):
- `bibtex.json` ← từ M2 output (mảng JSON)
- `references.json` ← từ M1 output (mảng JSON)

`elements.jsonl` **không copy vào M3**: pipeline đọc trực tiếp bên trong ZIP `M2_range_*_tables.zip` để tính feature **`cite_count`** (đếm số lần `citation_key` xuất hiện trong `\cite{...}` của toàn văn). Notebook truyền `elements_zip=M2_ZIP`; CLI dùng `--elements-zip`. Thiếu file → `cite_count = 0` cho mọi cặp; pipeline vẫn chạy nhưng in warning.

Và nhãn manual tại `data/labels/`:
- `manual/{arxiv_id}.json` ← sau khi import CSV

### 2. Chạy pipeline (1 dòng lệnh)

```powershell
# Chạy notebook (mục Chạy pipeline) hoặc:
python -m src.m3_matching.prepare_dataset --k 1 --seed 42
```

**Tham số:**
- `--k`: Số người nhóm (quyết định split size)
- `--seed`: Số cố định để lặp lại kết quả
- `--max-auto`: Giới hạn số auto papers (nếu dataset quá lớn)
- `--demo`: Chế độ thử nghiệm dữ liệu mẫu nhỏ
- `--elements-zip`: ZIP M2 chứa `elements.jsonl` (đọc trực tiếp, không giải nén)
- `--elements-path`: đường dẫn `elements.jsonl` rời (mặc định `<tables-dir>/elements.jsonl`)
- `--zip-auto`: gộp `labels/automatic/*.json` thành `labels/automatic/automatic.zip`

### 3. Output Parquet sẵn sàng

Ghi vào `prepared_dataset/` (cùng cấp `tables/`, không phải trong `tables/`):

```
M3_matching/range_{RANGE_ID}/prepared_dataset/
├── train_pairs.parquet    ← Dữ liệu huấn luyện (~70%)
├── valid_pairs.parquet    ← Dữ liệu kiểm tra khi phát triển (~10%)
├── test_pairs.parquet     ← Dữ liệu đánh giá MRR@5 (~20%)
├── dataset_pairs.parquet  ← Toàn bộ dữ liệu
└── poster_feature_distribution.png
```

---

## Notebook Workflow (từng Cell)

File notebook: `src/m3_matching/M3_matching.ipynb` (24 cells)

| Cell | Nội dung | Input | Output |
|------|---------|-------|--------|
| 1-2 | Setup: clone repo, cài dependencies, chạy unit tests | GitHub branch | ✅ Tests pass |
| 3-4 | Mount Google Drive, cấu hình đường dẫn | Drive + `RANGE_ID` | Paths ready |
| 5 | Load M1 + M2 → `tables/` | Drive folders + M2 ZIP | `bibtex.json`, `references.json` (`elements.jsonl` đọc trong ZIP) |
| 6 | Export CSV templates (5 papers) | BibTeX + References | `labels/manual/*.csv` (chờ tick) |
| 7 | **MANUAL WORK:** Tick `is_verified=YES` + import CSV | CSV (bạn sửa) | `labels/manual/*.json` |
| 8 | **AUTO:** Run pipeline | Labels + tables | `train/valid/test_pairs.parquet` |
| 9 | Visualization: feature distribution | Parquet files | PNG charts |
| 10 | Summary: deliverables checklist | All files | ✅ Done |

**⏳ Chỉ cần bạn làm Cell 7:** Tick checkbox → Code làm phần còn lại

---

## Load Data cho Người 2 (Model Training)

```python
import pandas as pd
from src.m3_matching.features import feature_names

# Đọc 3 tập
train_df = pd.read_parquet("prepared_dataset/train_pairs.parquet")
valid_df = pd.read_parquet("prepared_dataset/valid_pairs.parquet")
test_df = pd.read_parquet("prepared_dataset/test_pairs.parquet")

# Lấy features + label
features = feature_names()  # ['title_levenshtein', 'title_token_sort', ..., 'cite_count']
X_train = train_df[features]
y_train = train_df["label"]

# Sẵn sàng huấn luyện mô hình
from sklearn.ensemble import RandomForestClassifier
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Đánh giá trên test set
from sklearn.metrics import accuracy_score
y_pred = model.predict(test_df[features])
print(f"Test Accuracy: {accuracy_score(test_df['label'], y_pred):.4f}")
```

> **Cột dữ liệu:** mỗi dòng Parquet có 20 cột: 14 features + `arxiv_id`, `partition`, `citation_key`, `ref_arxiv_id`, `groundtruth_arxiv_id`, `label`. Khi huấn luyện chỉ dùng `feature_names()` + `label`; **bỏ** `groundtruth_arxiv_id`, `ref_arxiv_id`, `citation_key` để tránh leakage.

---

## Từng file / từng hàm

### `cleaning.py`
| Hàm | Chức năng |
| --- | --- |
| `normalize_title` | Lowercase, bỏ LaTeX/HTML, bỏ đuôi `arXiv preprint`/URL/DOI, giữ nội dung math (`Top-$k$` → `top k`), giải mã accent |
| `normalize_authors` | `Vaswani, Ashish` và `Ashish Vaswani` → cùng dạng `last, initial`; giữ tiền tố họ (`van der Berg`) |
| `normalize_year` | `int` / `"2017"` / ISO → `int` hoặc `None` |
| `normalize_doi` | Bỏ tiền tố `https://doi.org/`, `doi:`, lowercase |
| `prepare_bibtex_record` / `prepare_reference_record` | Thêm field `*_norm`, **không** sửa bảng gốc; chuẩn hóa `ref_arxiv_id` (bỏ `arXiv:`/URL và `vN`) |

### `labelling.py`
| Hàm | Chức năng |
| --- | --- |
| `auto_match_one` | Heuristic: DOI → exact title → fuzzy title + tác giả + năm; chỉ refs **cùng** paper; trả `ref_arxiv_id` hoặc `None` |
| `auto_label_publication` | Chạy matcher cho **mọi** BibTeX entry của 1 paper |
| `load_labels` / `save_labels` | Đọc/ghi `labels/manual|automatic/{arxiv_id}.json` |
| `validate_label_quota` | Raise nếu thiếu 5 papers / 20 entries / 100 tổng / 10% auto |

### `features.py`
| Hàm | Chức năng |
| --- | --- |
| `title_similarity`, `author_overlap`, `year_distance` | Tín hiệu so khớp cơ bản |
| `cite_context_features` | Ngữ cảnh `\cite` từ M2 (nếu có) |
| `pair_feature_vector` | Vector 14 float cố định cho cặp (bib, ref) |
| `feature_names` | Tên 14 cột, phải khớp thứ tự vector |

### `split.py`

`split_publications` → `dict[arxiv_id, "train"|"valid"|"test"]`, chia **theo paper** (không theo pair), `seed` để reproduce.

### `model.py`
| Hàm | Chức năng |
| --- | --- |
| `build_candidate_matrix` | `citation_key`, `ref_arxiv_id`, ma trận 0/1; GT không có trong refs → hàng 0 |
| `train_model` | Train từ `pair_feature_vector`; lưu `model_m3.joblib` |
| `predict_top5` | Score mọi ref cùng paper, sort, lấy top-5, pad `None` nếu thiếu |

### `evaluate.py`

`reciprocal_rank` = `1/rank` hoặc `0`; `mrr_at_k` = trung bình trên `|Q|`; `evaluate_split` ghi `metrics_m3.json`.

### `tables.py` / `pipeline.py` / `run_m3.py` / `analyze.py`

`tables.py`: `build_prediction_row` pad/cắt `cand_1`…`cand_5`, ghi `predictions.jsonl`.  
`run_milestone3`: label → split/train → predict → MRR test → predictions → export HF.  
`analyze.py`: số liệu cho poster (`n_manual`, `n_auto`, `|Q|`, tỷ lệ GT null, coverage `cand_1`).

### `export_hf.py`

```text
data/hf_dataset/README.md          # YAML configs, KHÔNG custom loading script
data/hf_dataset/data/papers/*.parquet
data/hf_dataset/data/references/*.parquet
data/hf_dataset/data/elements/*.parquet
data/hf_dataset/data/hierarchy/*.parquet
data/hf_dataset/data/bibtex/*.parquet
data/hf_dataset/data/predictions/*.parquet
```

---

## Metric MRR@5

\[
\mathrm{MRR@5} = \frac{1}{|Q|} \sum_i \frac{1}{\mathrm{rank}_i}
\]

- \(|Q|\) = số BibTeX **đã label** trên test
- `rank_i` = vị trí GT trong top-5 (`cand_1` = hạng 1)
- GT ngoài top-5 hoặc GT = `null` → entry đó 0 điểm

Được phép post-process (lọc trùng candidate, boost DOI exact...). Nhóm dùng LLM/pretrained model bị chấm tách nhóm — ghi rõ trên poster.

---

## Việc **không** làm ở M3

- Không đổi schema 6 bảng.
- Không nhét nested JSON vào Parquet.
- Không đưa paper unlabeled vào `predictions`.
- Poster A2 + Jupyter Book là việc nhóm khác/file khác.

---

## Kiểm Tra & Validation

### Unit tests
```powershell
python -m pytest tests/test_m3_matching.py -v
```
✅ 28/28 tests pass

| Nhóm | Test | Nội dung kiểm tra |
|------|------|-------------------|
| Cleaning (14) | `test_normalize_title` | Bỏ LaTeX/markup, giữ nội dung tiêu đề |
| | `test_normalize_title_decodes_latex_accents_before_braces` | `Schr\"{o}dinger` → `schrodinger`, không tách chữ |
| | `test_normalize_title_strips_citation_tails` | Bỏ đuôi `arXiv preprint`, URL, DOI |
| | `test_normalize_title_keeps_math_content` | `Top-$k$` → `top k` (không mất `k`) |
| | `test_normalize_title_strips_html_tags` | Bỏ `<i>`, `<sub>`... |
| | `test_normalize_authors` | Chuẩn hóa tên + bỏ `et al.` |
| | `test_normalize_authors_keeps_name_particles_consistent` | `van der Berg` / `de la Cruz` nhất quán |
| | `test_normalize_authors_splits_newlines` | Tách tác giả theo xuống dòng |
| | `test_normalize_year` | `int`, `YYYY`, `YYYY-MM-DD`, năm sai → `None` |
| | `test_normalize_doi` | Bỏ `https://doi.org/`, `doi:`, lowercase |
| | `test_reference_doi_from_external_ids` | Lấy DOI từ `externalIds.DOI` |
| | `test_prepare_records` | `prepare_bibtex_record` / `prepare_reference_record`, không sửa dict gốc |
| | `test_prepare_reference_normalizes_arxiv_id` | `arXiv:1706.03762v5` → `1706.03762` |
| | `test_prepare_bibtex_accepts_alias_columns` | Nhận cả `bib_title`, `bib_authors`, `bib_year`, `bib_doi` |
| Labelling (4) | `test_auto_match_one` | Auto-label khớp exact title/DOI |
| | `test_auto_match_doi_with_prefix` | DOI có prefix vẫn khớp |
| | `test_validate_label_quota` | Quota manual/auto đúng quy định |
| | `test_automatic_labels_zip_roundtrip` | Zip/đọc lại `labels/automatic.zip` đúng nhãn |
| Features (3) | `test_features_dimensions` | Đủ 14 đặc trưng |
| | `test_feature_doi_match_normalizes_prefixes` | `doi_match` chuẩn hóa prefix |
| | `test_feature_year_missing_sentinel` | Sentinel khi thiếu năm |
| Dataset (3) | `test_build_paper_pairs` | Sinh cặp positive/negative đúng |
| | `test_build_paper_pairs_dedups_reference_arxiv_ids` | Dedup reference theo `ref_arxiv_id` |
| | `test_build_citation_context_and_cite_count_feature` | `cite_count` lấy từ `elements.jsonl` |
| Manual tool (2) | `test_manual_template_does_not_autofill_groundtruth` | Template không tự điền groundtruth |
| | `test_import_manual_csv_requires_verified_rows` | Chỉ import dòng `is_verified=YES` |
| Split (2) | `test_split_publications` | Chia train/valid/test theo publication |
| | `test_split_rejects_invalid_k` | Báo lỗi khi `k` không hợp lệ |

Chỉ chạy test phần làm sạch dữ liệu (Task 1):
```powershell
python -m pytest tests/test_m3_matching.py -v -k "normalize or prepare"
```

Kiểm tra nhanh cleaning bằng Python:
```python
from src.m3_matching.cleaning import normalize_title, prepare_reference_record

assert normalize_title(
    "Outcome Monitors: Recovery Affordances for Silent Tool Failures. "
    "arXiv preprint. https://arxiv.org/abs/2608.19303v1"
) == "outcome monitors recovery affordances for silent tool failures"

assert normalize_title("Beyond Top-$k$ Retrieval") == "beyond top k retrieval"

assert prepare_reference_record(
    {"ref_arxiv_id": "arXiv:1706.03762v5", "ref_title": "Attention"}
)["ref_arxiv_id_norm"] == "1706.03762"
```

### Demo pipeline
```powershell
python -m src.m3_matching.prepare_dataset --demo
```
→ Chạy trên dữ liệu mẫu nhỏ để kiểm tra toàn bộ workflow

---

## Troubleshooting

| Vấn đề | Nguyên nhân | Giải pháp |
|--------|-----------|----------|
| `ModuleNotFoundError: No module named 'src'` | Chưa chạy cell setup sau khi restart runtime, hoặc kernel không có project trong `sys.path` | Chạy lại cell Setup (clone/pull + `sys.path.insert`) rồi chạy tiếp |
| Import CSV báo lỗi "No valid labels" | Không có dòng `is_verified=YES` | Mở CSV, tick ≥1 dòng, lưu lại |
| Features bị NaN | Thiếu dữ liệu input | Kiểm tra `references.json` + `bibtex.json` |
| Split không cân bằng | `k` không khớp | Đếm papers, kiểm tra `--k` parameter |
| Parquet quá lớn | Auto pool quá nhiều | Dùng `--max-auto 450` để giới hạn |

---

## Submission Checklist (cho cả nhóm)

- [ ] ≥5 papers được gắn nhãn manual (mỗi ≥20 entries)
- [ ] Tổng ≥100 entries manual (hoặc ≥100k per person)
- [ ] ≥10% papers auto ngoài manual pool
- [ ] 4 file Parquet được sinh: train/valid/test/dataset
- [ ] Mỗi file có 20 cột: 14 features + `arxiv_id`, `partition`, `citation_key`, `ref_arxiv_id`, `groundtruth_arxiv_id`, `label`
- [ ] Kiểm tra không có NaN trong features
- [ ] Code push lên GitHub branch `M3-matching`
- [ ] README.md cập nhật hướng dẫn chạy
- [ ] Poster A2: trình bày 14 features + lý do thiết kế
- [ ] Hugging Face dataset: upload 6 bảng Parquet (papers, references, elements, hierarchy, bibtex, predictions)

---

## FAQ

**Q: Phải đợi người khác gắn nhãn xong mới chạy pipeline?**
A: Không. Khi có ≥2 papers manual (≥40 entries), chạy pipeline → auto labels → dataset sẵn sàng. Sau đó người khác import, merge labels, chạy lại pipeline.

**Q: Có thể skip gắn nhãn manual mà chỉ dùng auto?**
A: Không. Đề bài bắt buộc manual ≥5 papers × ≥20 entries. Auto chỉ dùng cho papers ngoài manual pool.

**Q: Làm sao để reproduce kết quả?**
A: Dùng `--seed 42` (mặc định). Nếu input bằng nhau → kết quả bằng nhau (100% reproducible).

**Q: 14 features có thể giải thích sao?**
A: Xem bảng ở mục 4. Mỗi feature có ý tưởng lý thuyết phục vụ Poster A2.

---

## Liên hệ & Support

- **README tổng quan:** `src/m3_matching/README.md` (toàn bộ chi tiết nằm trong file này)
- **Tests:** `tests/test_m3_matching.py`
- **Notebook:** `src/m3_matching/M3_matching.ipynb`
- **Code modules:** `src/m3_matching/*.py`
