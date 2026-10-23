# Milestone 3 — Reference Matching Pipeline

**Người làm M3 đọc file này trước khi mở code.**

Đề đầy đủ: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching>

Phụ thuộc: M1 có bảng `references` (ref **có arXiv ID**), M2 có bảng `bibtex` (+ hierarchy nếu dùng feature ngữ cảnh).

## Bạn đang làm gì?

Với **cùng một paper**, ghép mỗi entry BibTeX (M2) với crawled reference (M1).

- Trong 1 paper: `m` bib entries × `n` refs có arXiv ID = ma trận 0/1.
- Mỗi entry labeled: **tối đa 1** ô “yes”; không khớp ref nào → hàng toàn 0.
- Model trả **top 5** `ref_arxiv_id`. Metric: **MRR@5**.
- Cuối cùng xuất **6 bảng Parquet** lên Hugging Face (papers, references, elements, hierarchy, bibtex, predictions).

Chạy:

```bash
python -m src.m3_matching.run_m3
```

---

## Thứ tự nên code

```text
cleaning.py      → chuẩn hóa title/author/year
labelling.py     → ground truth (manual + auto) + kiểm quota
features.py      → vector cặp (bib, ref) — nhớ viết lý do từng feature
split.py         → chia THEO PAPER, không theo từng entry
model.py         → train + predict_top5
evaluate.py      → MRR@5
tables.py        → PredictionRow
pipeline.py      → nối
export_hf.py     → Parquet + README YAML
analyze.py       → số poster
```

---

## Labelling — đọc kỹ, dễ thiếu điểm

Ghép **trong cùng publication** thôi (bib của paper A không khớp ref của paper B).

**Manual (người gán):**

- ≥ **5** publications
- Mỗi paper manual ≥ **20** entry đã gán
- Tổng entry đã gán (manual pool) ≥ **100**

**Auto (regex / similarity, code trong `auto_match_one`):**

- ≥ **10%** số publication **ngoài** nhóm manual
- Paper được chọn auto: phải gán **mọi** BibTeX entry của paper đó

File (không commit nếu chứa data lớn; format bắt buộc ghi rõ — đã chốt):

`data/labels/{arxiv_id}.jsonl`

```json
{"citation_key": "vaswani2017", "groundtruth_arxiv_id": "1706.03762", "source": "manual"}
{"citation_key": "someBook", "groundtruth_arxiv_id": null, "source": "auto"}
```

- `source`: chỉ `manual` hoặc `auto`
- `groundtruth_arxiv_id`: arXiv ID của ref đúng, hoặc `null` nếu không có trong crawled refs

---

## Split (theo publication)

| Tập | Gồm |
| --- | --- |
| **test** | 1 paper **manual** + 1 paper **auto** |
| **valid** | 1 paper **manual** + 1 paper **auto** |
| **train** | mọi paper labeled còn lại |

Chỉ paper nằm trong 3 tập này mới có hàng ở bảng `predictions`. Paper unlabeled → không xuất.

---

## Metric MRR@5 (test, 2 papers ở trên)

\[
\mathrm{MRR@5} = \frac{1}{|Q|} \sum_i \frac{1}{\mathrm{rank}_i}
\]

- \(|Q|\) = số BibTeX **đã label** trên test
- `rank_i` = vị trí GT trong top-5 (`cand_1` = hạng 1)
- GT không nằm top-5, hoặc GT = `null` → điểm entry đó = **0**

Được phép post-process (lọc trùng candidate, boost DOI exact, …).

Nhóm dùng LLM / pretrained model sẽ bị chấm **tách** nhóm chỉ dùng model cổ điển — ghi rõ trên poster.

---

## Từng file / từng hàm

### `cleaning.py`

| Hàm | Code cái gì |
| --- | --- |
| `normalize_title` | lower, bỏ punct dư, optional stopword — ghi poster vì sao |
| `normalize_authors` | `Vaswani, Ashish` vs `Ashish Vaswani` → cùng dạng (last name + initials) |
| `normalize_year` | int / `"2017"` / ISO → `int` hoặc `None` |
| `prepare_bibtex_record` / `prepare_reference_record` | Thêm field `*_norm`, **không** sửa bảng gốc |

### `labelling.py`

| Hàm | Code cái gì |
| --- | --- |
| `auto_match_one` | Heuristic: DOI → title giống → fuzzy (rapidfuzz) + overlap author. Chỉ refs **cùng** paper. Trả `ref_arxiv_id` hoặc `None` |
| `auto_label_publication` | Chạy matcher cho **mọi** bib entry của 1 paper |
| `load_labels` / `save_labels` | jsonl như trên |
| `validate_label_quota` | Raise nếu thiếu 5 papers / 20 / 100 / 10% auto |

### `features.py` — bắt buộc giải thích từng feature (README + poster)

Được dùng **hierarchy M2** (câu chứa `\cite{key}`, heading gần nhất, số lần cite).

| Hàm | Code cái gì |
| --- | --- |
| `title_similarity` | 0..1 (Levenshtein / Jaccard / TF-IDF cosine) |
| `author_overlap` | Jaccard last names |
| `year_distance` | `abs(y1-y2)`; thiếu năm → sentinel, ghi rõ |
| `cite_context_features` | Optional từ cây M2 |
| `pair_feature_vector` | Ghép thành list[float] **cố định** |
| `feature_names` | Tên cột **khớp** vector — đừng lệch |

Gợi ý tối thiểu (phải viết “ý tưởng” khi implement): title giống nhau thường cùng paper; author overlap giảm false positive cùng title; year loại bản preprint lệch thập kỷ.

### `split.py`

`split_publications` → `dict[arxiv_id, "train"|"valid"|"test"]`. Tách manual/auto theo field `source`. `seed` để reproduce.

### `model.py`

Paradigm do nhóm chọn (classification cặp / ranking / …) — ghi poster.

| Hàm | Code cái gì |
| --- | --- |
| `build_candidate_matrix` | keys, ref ids, matrix 0/1; GT không có trong refs → hàng 0 |
| `train_model` | X,y từ `pair_feature_vector`; sklearn; lưu `data/tables/model_m3.joblib` (gitignore) |
| `predict_top5` | Score mọi ref cùng paper, sort, cắt 5, pad `None` nếu `n<5` |

### `evaluate.py`

| Hàm | Code cái gì |
| --- | --- |
| `reciprocal_rank` | `1/rank` hoặc `0` |
| `mrr_at_k` | Trung bình trên `|Q|` |
| `evaluate_split` | MRR@5 (+ optional hit@1/@5) → nhét `metrics_m3.json` |

### `tables.py`

`build_prediction_row`: pad/cắt đúng `cand_1`…`cand_5`.  
`write_predictions_table`: `data/tables/predictions.jsonl`.

Cột: `arxiv_id`, `partition`, `citation_key`, `groundtruth_arxiv_id` (nullable), `cand_1`…`cand_5` (nullable).

### `export_hf.py` — nộp data cuối

```text
data/hf_dataset/README.md          # YAML configs, KHÔNG custom loading script
data/hf_dataset/data/papers/*.parquet
data/hf_dataset/data/references/*.parquet
data/hf_dataset/data/elements/*.parquet
data/hf_dataset/data/hierarchy/*.parquet
data/hf_dataset/data/bibtex/*.parquet
data/hf_dataset/data/predictions/*.parquet
```

Card YAML (mỗi bảng một `config_name`, `path: data/<tên>/*.parquet`, `split: train`).  
Cột phẳng. Upload Hub theo hướng dẫn Lab Instructors (M3 mới nộp dataset).

### `pipeline.py` / `run_m3.py` / `analyze.py`

`run_milestone3`: label → split/train → predict mọi labeled entry → MRR test → ghi predictions → export HF.  
`--export-only`: chỉ đóng gói parquet nếu tables đã có.

---

## Việc **không** làm ở M3

- Không đổi schema 6 bảng.
- Không nhét nested JSON vào Parquet.
- Không đưa paper unlabeled vào `predictions`.
- Poster A2 + Jupyter Book = việc nhóm khác / file khác, không nằm trong stub này.

## Xong M3 khi nào?

- [ ] `validate_label_quota` pass
- [ ] Split đúng 1+1 test, 1+1 valid
- [ ] Mỗi labeled entry có đúng 1 GT hoặc `null`
- [ ] Test in ra MRR@5
- [ ] 6 thư mục parquet + dataset card YAML
- [ ] Poster/README liệt kê **từng feature và lý do**
