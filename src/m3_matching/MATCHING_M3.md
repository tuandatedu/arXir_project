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

### Yêu cầu (theo đề bài cho 1 người):
- ≥5 papers × ≥20 entries/paper = ≥100 tổng
- Nhóm k người: ≥5k papers, ≥100k entries

### Workflow (3 bước):

**Step 1: Export CSV templates**
```powershell
# Chạy notebook Cell 12 hoặc command:
python -m src.m3_matching.manual_tool --export-template 2310.12345
```
→ File: `labels/manual/2310.12345.csv` có cột:
- `citation_key`, `bib_title`, `bib_authors`, ... (read-only)
- `suggested_ref_arxiv_id` ← gợi ý tự động
- `suggested_score` ← độ tin cậy gợi ý
- **`is_verified`** ← **BẠN TÁC CÁC DÒNG HỢP LỆ** (YES/NO)
- `groundtruth_arxiv_id` ← để trống (code auto-fill)

**Step 2: Kiểm tra bằng mắt trên arXiv**
1. Mở CSV trong Excel
2. Duyệt từng dòng, tìm trên arXiv.org
3. Nếu `suggested_ref_arxiv_id` đúng → tick `is_verified=YES`
4. Nếu sai hoặc không chắc → để trống hoặc điền `groundtruth_arxiv_id` thủ công

⏱ **Thời gian:** ~1 giờ cho ~100 entries

### Step 3: Import CSV → JSON
```powershell
# Chạy notebook Cell 13 hoặc command:
python -m src.m3_matching.manual_tool --import-csv labels/manual/2310.12345.csv
```
→ Code tự động:
- Đọc CSV
- Lọc dòng `is_verified=YES`
- **Auto-fill `groundtruth_arxiv_id = suggested_ref_arxiv_id`** ← nhãn thực
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

**Output:** JSON files tại `labels/automatic/{arxiv_id}.json`

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

**Output:** DataFrame Parquet với 14 + 2 cột = 16 cột:
```
[14 features] + [arxiv_id, label]
```

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

Cần 2 bảng tại `data/tables/`:
- `bibtex.json` ← từ M2 output
- `references.json` ← từ M1 output

Và nhãn manual tại `data/labels/`:
- `manual/{arxiv_id}.json` ← sau khi import CSV

### 2. Chạy pipeline (1 dòng lệnh)

```powershell
# Chạy notebook Cell 14 hoặc:
python -m src.m3_matching.prepare_dataset --k 1 --seed 42
```

**Tham số:**
- `--k`: Số người nhóm (quyết định split size)
- `--seed`: Số cố định để lặp lại kết quả
- `--max-auto`: Giới hạn số auto papers (nếu dataset quá lớn)
- `--demo`: Chế độ thử nghiệm dữ liệu mẫu nhỏ

### 3. Output Parquet sẵn sàng

```
data/tables/
├── train_pairs.parquet    ← Dữ liệu huấn luyện (~70%)
├── valid_pairs.parquet    ← Dữ liệu kiểm tra khi phát triển (~10%)
├── test_pairs.parquet     ← Dữ liệu đánh giá MRR@5 (~20%)
└── dataset_pairs.parquet  ← Toàn bộ dữ liệu
```

---

## Notebook Workflow (từng Cell)

---

## Notebook Workflow (từng Cell)

File notebook: `src/m3_matching/M3_matching.ipynb` (19 cells)

| Cell | Nội dung | Input | Output |
|------|---------|-------|--------|
| 1-2 | Setup: clone repo, cài dependencies, chạy unit tests | GitHub branch | ✅ Tests pass |
| 3-4 | Mount Google Drive, cấu hình đường dẫn | Drive + RANGE_ID | Paths ready |
| 5 | Load M1 references + M2 BibTeX → JSON | Drive folders | `tables/references.json`, `bibtex.json` |
| 6 | Export CSV templates (5 papers) | BibTeX + References | `labels/manual/*.csv` (chờ bạn tick) |
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

---

## Kiểm Tra & Validation

### Unit tests
```powershell
python -m pytest tests/test_m3_matching.py -v
```
✅ 27/27 tests pass

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
- [ ] Mỗi file có 16 cột: 14 features + arxiv_id + label
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

- **README:** `src/m3_matching/README.md`
- **Tests:** `tests/test_m3_matching.py`
- **Notebook:** `src/m3_matching/M3_matching.ipynb`
- **Code modules:** `src/m3_matching/*.py`
