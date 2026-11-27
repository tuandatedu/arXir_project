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

**Manual labeling:** Dùng đúng ba giá trị `review_status`: `match`, `no_match`, `unknown`. GT xác nhận phải có ID và `match`; xác nhận không có candidate đúng dùng GT trống và `no_match`; chưa xác định dùng `unknown`.

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
        │   └── automatic/     # một JSON cho mỗi publication được gán nhãn
        └── prepared_dataset/
            ├── dataset_pairs.parquet
            ├── train_pairs.parquet
            ├── valid_pairs.parquet
            ├── test_pairs.parquet
            └── poster_feature_distribution.png
```

- `elements.jsonl` **không nằm trong M3**: pipeline đọc trực tiếp bên trong ZIP `M2_range_*_tables.zip` để tính `cite_count` (notebook truyền `elements_zip=M2_ZIP`).
- Auto labels được lưu riêng tại `labels/automatic/{arxiv_id}.json`. Pipeline đọc được ZIP cũ để tương thích, nhưng không tạo ZIP mới.
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

**Ưu tiên:** Volume cao (nhiều BibTeX + References)
- Paper A: 2500 BibTeX | 500 References → **CHỌN** (nhiều data, nhiều matching)
- Paper B: 30 BibTeX | 50 References → bỏ qua (ít data dù coverage cao)

**Lợi ích:**
- Nhiều entries để manual label → dataset lớn hơn
- Nhiều references → nhiều matching opportunities
- Coverage ≥10% đảm bảo quality (không quá ít refs)

### Yêu cầu (theo đề bài cho 1 người):
- ≥5 papers × ≥20 entries/paper = ≥100 tổng
- Nhóm k người: ≥5k papers, ≥100k entries

### Workflow (3 bước):

**Step 1: Export CSV templates**

Export a CSV with BibTeX fields and suggested reference candidates. Suggestions are for review only.

**Step 2: Review and fill ground truth**

Compare each BibTeX entry with its candidates. If the correct candidate is in the pool, enter its ID in `groundtruth_arxiv_id` and set `review_status=match`. If no candidate is correct, set `review_status=no_match`; leave GT blank when it is unknown, but retain the true ID when it is known and outside the pool. Use `unknown` when review has not established either outcome.

| Case | `groundtruth_arxiv_id` | Import behavior |
|---|---|---|
| Candidate confirmed as the cited work | Enter its `ref_arxiv_id`; set `review_status=match` | Imported as a manual positive label |
| Suggested candidate is wrong, another reference is found | Enter the correct `ref_arxiv_id`; set `review_status=match` | Imported as a manual positive label |
| Not reviewed or unresolved | Leave GT blank; set `review_status=unknown` | Retained in labels for audit; omitted from training pairs |
| Reviewed; no matching reference in the candidate pool, GT unknown | Leave GT blank; set `review_status=no_match` | Kept as an all-zero query |
| GT known but absent from candidate pool | Keep true GT; set `review_status=no_match` | Available candidates are all 0; GT retained for coverage |

### Step 3: Import CSV to JSON

Run `python -m src.m3_matching.manual_tool --import-csv labels/manual/<paper_id>.csv`.

The importer uses three review states: `match`, `no_match`, and `unknown`. `match` means the correct candidate is in the pool. `no_match` means none of the available candidates is correct; its GT may be blank or may retain the known true ID when that ID is outside the pool. A `no_match` GT that is present in the pool is invalid. `unknown` is retained in labels but omitted from training pairs. Suggested IDs are never accepted automatically. A GT outside the candidate pool yields all-zero labels for available candidates and is recorded as a candidate-coverage issue in `dataset_report.json`. Legacy CSVs without `review_status` remain accepted; non-empty GT is treated as explicitly supplied and blank GT as `unknown`.

**Phân biệt `unknown` và `no_match`:** `unknown` = chưa xác định được ground truth (heuristic không đủ tin cậy hoặc reviewer chưa kết luận); nó **không** chứng minh rằng không có candidate đúng. `no_match` = reviewer đã xác nhận không candidate nào trong pool là đúng. Vì vậy không được tự động đổi `unknown` thành `no_match` để tránh tạo negative labels sai.

Automatic vẫn gán một label record cho **mọi** BibTeX entry của publication được chọn; `unknown` nằm trong label records để kiểm toán nhưng không sinh pairs. Do đó tập pairs/evaluation là một tập con của toàn bộ query. `dataset_report.json` ghi riêng `queries_total`, `queries_with_known_gt`, `queries_unknown`, `queries_with_pairs`, `queries_without_pairs`, `gt_outside_candidate_pool` và `candidate_coverage` theo cả Manual/Automatic lẫn train/valid/test.

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

**Output:** Mỗi publication có một JSON tại `labels/automatic/{arxiv_id}.json`.

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
   - `label=0` if the ground truth ID is known but this candidate has a different ID.
   - GT đã xác nhận nhưng **ngoài candidate pool**: sinh hàng toàn `0`, vẫn giữ `groundtruth_arxiv_id` thật để tính Candidate Coverage.
   - `no_match` (GT trống, reviewer xác nhận): sinh hàng toàn `0`.
   - `unknown` (GT trống, chưa xác định): **không** sinh pairs, để tránh negative labels sai.

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

File notebook: `notebooks/m3/M3_matching.ipynb` (24 cells)

| Cell | Nội dung | Input | Output |
|------|---------|-------|--------|
| 1-2 | Setup: clone repo, cài dependencies, chạy unit tests | GitHub branch | ✅ Tests pass |
| 3-4 | Mount Google Drive, cấu hình đường dẫn | Drive + `RANGE_ID` | Paths ready |
| 5 | Load M1 + M2 → `tables/` | Drive folders + M2 ZIP | `bibtex.json`, `references.json` (`elements.jsonl` đọc trong ZIP) |
| 6 | Export CSV templates (5 papers) | BibTeX + References | `labels/manual/*.csv` (chờ tick) |
| 7 | **MANUAL WORK:** Fill `groundtruth_arxiv_id` + import CSV | CSV (bạn sửa) | `labels/manual/*.json` |
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

- `rank_i` = vị trí GT trong top-5 (`cand_1` = hạng 1)
- GT ngoài top-5 → entry đó 0 điểm.

**Phạm vi đánh giá (bắt buộc ghi rõ khi báo cáo):**

- `MRR@5 (evaluated)`: \(|Q|\) = số query có **GT đã xác nhận và nằm trong candidate pool**. Chỉ nhóm này mới rank được.
- `MRR@5 (strict)`: \(|Q|\) = toàn bộ query đã label trên test; `unknown`, `no_match` và GT ngoài pool đều tính 0 điểm. Cách này khớp nghĩa đen "mọi entry đã label" nhưng bị pha loãng bởi query không có GT.
- Luôn báo kèm `n_evaluated`, `n_labeled` và `candidate_coverage = n_evaluated / n_labeled_with_known_gt`.
- **Không** báo MRR@5 như thể đã đánh giá toàn bộ 144k query khi `unknown` bị loại khỏi pairs. `dataset_report.json` cung cấp sẵn các mẫu số trong `evaluation_scope`.

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
✅ 33/33 tests pass

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
| Labelling (3) | `test_auto_match_one` | Auto-label khớp exact title/DOI |
| | `test_auto_match_doi_with_prefix` | DOI có prefix vẫn khớp |
| | `test_validate_label_quota` | Quota manual/auto đúng quy định |
| Features (3) | `test_features_dimensions` | Đủ 14 đặc trưng |
| | `test_feature_doi_match_normalizes_prefixes` | `doi_match` chuẩn hóa prefix |
| | `test_feature_year_missing_sentinel` | Sentinel khi thiếu năm |
| Dataset (5) | `test_build_paper_pairs` | Sinh cặp positive/negative đúng |
| | `test_build_paper_pairs_dedups_reference_arxiv_ids` | Dedup reference theo `ref_arxiv_id` |
| | `test_build_citation_context_and_cite_count_feature` | `cite_count` lấy từ `elements.jsonl` |
| | `test_gt_null_review_states_and_gt_outside_pool` | `unknown` không sinh pair; `no_match` và GT ngoài pool sinh hàng toàn 0, giữ GT |
| | `test_pipeline_query_stats_match_parquet` | Thống kê query khớp Parquet thực tế sau pipeline |
| Manual tool (2) | `test_manual_template_does_not_autofill_groundtruth` | Template không tự điền groundtruth |
| `test_import_manual_csv_uses_only_nonempty_groundtruth` | Ch? import d?ng c? ground truth |
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
| Import reports no valid labels | No ground truth IDs were entered | Enter a confirmed reference ID in `groundtruth_arxiv_id` |
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
- **Notebook:** `notebooks/m3/M3_matching.ipynb`
- **Code modules:** `src/m3_matching/*.py`
