# Milestone 2 — Hierarchical Parsing and Standardization

**Người làm M2 đọc file này trước khi mở code.**

Đề đầy đủ: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing>

Phụ thuộc: **M1 đã chạy xong**, có `data/working/{id}/vN/sources/`.

## Bạn đang làm gì?

Biến TeX thô thành dữ liệu có cấu trúc:

1. **Compilation path** — chỉ parse file LaTeX thật sự được compile.
2. **Cây phân cấp** mỗi version (Document → section → … → leaf).
3. **Cleanup + chuẩn hóa toán**.
4. **`\\bibitem` → BibTeX**.
5. **Dedup giữa các version** của cùng paper (nội dung + reference).

Chạy:

```bash
python -m src.m2_parsing.run_m2
```

---

## Thứ tự nên code

```text
gather.py       → biết file nào là “thật”
cleanup.py      → rửa TeX trước khi so khớp
hierarchy.py    → ra cây
bibitem.py      → ra list BibTeX / version
dedup.py        → gộp version, gán element_id
tables.py       → 3 bảng
pipeline.py + run_m2.py
analyze.py      → số report
```

---

## Output

```text
data/working/2310-12345/parsed/
  elements.jsonl
  hierarchy.jsonl
  bibtex.json
data/tables/elements.jsonl
data/tables/hierarchy.jsonl
data/tables/bibtex.jsonl
data/tables/metrics_m2.json
```

Ba bảng Hugging Face (cột phẳng, xem `src/common/schemas.py`):

| Bảng | Ý nghĩa |
| --- | --- |
| `elements` | 1 hàng / element **duy nhất** trên mọi version. Trùng content sau cleanup → **cùng** `element_id` |
| `hierarchy` | 1 hàng / cạnh parent→node của **từng** version |
| `bibtex` | Entry đã union field + 1 `citation_key` cho cả publication |

`element_id` = `{folder}#{discriminant}`, ví dụ `2310-12345#s1`.

Ví dụ đề: câu giống nhau 2 version = một element `s1`; version 1 gắn parent `h1`, version 2 gắn parent `h2`.

Version **không có TeX** (empty M1): **không skip** — ghi version rỗng (0 element) để thống kê coverage đúng.

---

## Từng file / từng hàm

### `gather.py` — multi-file

Root = file `.tex` có `\documentclass`.  
Theo `\input` / `\include` **bắc cầu**. Lệnh đã comment (`%`) = chữ thường, **không** include. File không nằm trên path = auxiliary, **bỏ**.

| Hàm | Code cái gì |
| --- | --- |
| `find_document_root` | Scan `*.tex`; bỏ `documentclass` trong comment. 0 file → `None` (empty version). Nhiều file → heuristic (tên `main`, path nông) + log |
| `strip_tex_line_comments` | Xóa từ `%` không escape tới hết dòng; giữ `\%` |
| `extract_include_targets` | Argument `\input` / `\include` sau khi strip comment. Cân nhắc `\input file` không ngoặc |
| `resolve_include_path` | Thử `target`, `target.tex`, relative current file rồi `source_dir`. Thiếu file → warning, không crash |
| `compilation_path` | DFS/BFS từ root, unique, đúng thứ tự |
| `concatenate_compilation_tex` | Ghép nội dung path (parser 1 pass). Có thể chèn marker comment `% FILE: ...` |

### `cleanup.py` — rửa + toán

Làm **trước** dedup full-text. **Không** xóa `figure` / `\includegraphics`.

| Hàm | Code cái gì |
| --- | --- |
| `remove_non_semantic_commands` | Tối thiểu theo đề: `\centering`, option `[htbp]`/`[H]`, `\midrule` (và `\hline`, `\toprule`, `\vspace`, …). Collapse whitespace |
| `normalize_inline_math` | `\(...\)`, `math` env → `$...$` |
| `normalize_block_math` | `$$`, `\[`, `equation*`, `align`, `displaymath` → `\begin{equation}...\end{equation}` (nếu giữ `align`, ghi rõ trong report) |
| `cleanup_element_content` | Strip/space cho **1 node** trước khi so chuỗi |
| `cleanup_document` | Gọi 3 bước trên theo thứ tự |

### `hierarchy.py` — cây

- Root = `document`.
- Level heading **tự suy** từ lệnh (`\chapter`, `\section`, `\subsection`, …), kể cả dạng `*`.
- **Leaf bắt buộc:** sentence (chấm câu), block formula, figure (**table cũng tính figure**).
- `itemize`/`enumerate`: list = cha, mỗi `\item` = `list_item`, rồi sentence bên trong.
- **Không** đưa section References/Bibliography vào cây.
- **Phải** gồm Acknowledgements và Appendix (kể cả `\section*`).

| Hàm | Code cái gì |
| --- | --- |
| `heading_level` | Map lệnh → số sâu (part/chapter/section/…) |
| `is_references_heading` | True → skip cả subtree |
| `is_acknowledgement_or_appendix` | Trả `'acknowledgement'` / `'appendix'` / `None` |
| `split_sentences` | **Không** tách trong toán, lệnh, viết tắt (`i.e.`, `et al.`, `Fig. 1`), URL, số `3.14` |
| `parse_tex_to_tree` | TeX đã concat + cleanup → `ParseNode`. TeX rỗng → root rỗng |

`kind` nên khớp `ELEMENT_KINDS` trong schema (`document`, `heading`, `paragraph`, `list`, `list_item`, `sentence`, `formula`, `figure`, `acknowledgement`, `appendix`). Thêm kind thì thống nhất cả nhóm.

### `bibitem.py` — trích reference từ TeX

| Hàm | Code cái gì |
| --- | --- |
| `extract_bibitems` | `\bibitem{key}` trong `thebibliography` → key, title, authors, year, doi, url, journal |
| `parse_bib_file` | File `.bib` sẵn (bibtexparser hoặc regex `@article{`) |
| `infer_entry_type` | journal→`article`, booktitle→`inproceedings`, else `misc`. Phải thuộc `BIBTEX_ENTRY_TYPES` |
| `collect_version_bibtex` | Gộp bibitem + mọi `.bib` trong `source_dir` |

### `dedup.py` — hai mức, **across versions**

**A. BibTeX**

- Cùng reference, khác citation key → chọn **1 key**, các `\cite{}` key cũ coi như đổi sang key đó (lưu mapping).
- **Union field**, không chọn 1 bản rồi vứt field bản kia.  
  Ví dụ đề: v1 `vaswani2017` {title, author, year} + v2 `vit_transformer` {title, author, doi} → 1 entry, đủ title+author+year+doi.

**B. Full-text**

- So `kind` + `content` **sau cleanup**.
- Trùng → cùng `element_id`. Hierarchy version khác có thể trỏ parent khác.

| Hàm | Code cái gì |
| --- | --- |
| `references_similar` | DOI giống, hoặc title+year+authors. **Không** chỉ so key |
| `choose_canonical_key` | Ví dụ key xuất hiện nhiều version nhất |
| `union_bib_fields` | Field non-empty thắng |
| `dedup_bibtex_across_versions` | Cluster (union-find) → `list[BibtexRow]` + `dict[old_key, canonical]` |
| `flatten_tree_with_placeholders` | Preorder `(node, parent)` |
| `assign_element_ids` | Lần đầu thấy content → discriminant mới (`s1`, `h1`, `root1`…). Version sau trùng → tái sử dụng id. `HierarchyRow` mỗi cạnh. `parent_id` non-null: không emit hàng cho root (hoặc quy ước sentinel — **chọn 1 cách, ghi vào đây khi implement**) |

### `tables.py` / `pipeline.py` / `run_m2.py` / `analyze.py`

| Hàm | Code cái gì |
| --- | --- |
| `save_publication_parsed` | Ghi parsed / paper để M3 không parse lại |
| `write_m2_tables` | 3 jsonl global |
| `parse_one_version` | gather → cleanup → tree + bib; empty → tree rỗng |
| `parse_one_publication` | Mọi version → `assign_element_ids` + `dedup_bibtex` |
| `run_milestone2` | `iter_publications()` từ M1, `track_run('m2')`, ghi tables + metrics |
| `parsing_stats` | success rate, coverage version, số element/bib **trước vs sau** dedup |

---

## Việc **không** làm ở M2

- Không crawl lại arXiv.
- Không train model matching (M3).
- Không bỏ Acknowledgements/Appendix.
- Không parse section References vào `elements`.

## Xong M2 khi nào?

- [ ] Mọi publication M1 được parse; empty version vẫn được ghi
- [ ] Chỉ file trên compilation path
- [ ] Leaf chỉ gồm sentence / block math / figure (table = figure)
- [ ] Math đã unified; clutter `\centering`/`[htbp]`/`\midrule` đã gỡ
- [ ] BibTeX 1 key / reference / paper; field đã union
- [ ] Element trùng giữa version dùng chung `element_id`
- [ ] Có `metrics_m2.json`
