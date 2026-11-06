# Báo cáo kỹ thuật M2 — cây phân cấp trước chuẩn hóa

> Tài liệu này mô tả trạng thái bàn giao của phần parser thô. Pipeline M2 đầy đủ
> hiện đã chạy qua `python -m src.m2_parsing.run_m2`; xem `README.md` và
> `report_m2.ipynb` để biết phần chuẩn hóa, BibTeX, dedup và thống kê cuối.

File này ghi lại phần M2 đã làm: build cây document → section → subsection … từ TeX nguồn, trước khi đi qua cleanup / BibTeX / dedup. Mục tiêu là có một cây raw đúng theo cấu trúc bài báo, để các bước sau dễ nối vào.

| Mục | Thông tin |
| --- | --- |
| Đề | Milestone 2 — Hierarchical Parsing |
| Phần đã hoàn thành | Gathering + cây cha–con theo từng version, chưa cleanup / BibTeX / dedup |
| Code | `src/m2_parsing/{gather,hierarchy,pipeline,run_m2,analyze}.py` |
| Test | `tests/test_m2_hierarchy.py` (14 test) |
| CLI | `python -m src.m2_parsing.run_m2` |
| Còn lại của nhóm | `cleanup.py`, `bibitem.py`, `dedup.py`, bảng HF `elements` / `hierarchy` / `bibtex` |

---

## 0. Chạy nhanh trong 10 phút

Từ root repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r src/requirements.txt
python -m pip install pytest

export PYTHONPATH=.
python -m pytest tests/test_m2_hierarchy.py -q
```

Kỳ vọng: 14 passed.

Nếu fail, xem mục 9.

---

## 1. Phạm vi làm tới đây

Đề yêu cầu M2 xử lý bài báo TeX theo kiểu:

1. Nhận `.tex` từ M1.
2. Tìm file chính có `\documentclass`.
3. Theo dõi `\input` / `\include`, bỏ file không dùng.
4. Xây cây Document → Section → Subsection → …
5. Tách câu / công thức / hình / bảng.
6. Không đưa References vào cây.
7. Xử lý nhiều kiểu bài, nhiều version.
8. Bàn giao cây raw ở từng version.

Tình trạng hiện tại:

| Yêu cầu đề M2 | Trạng thái | File |
| --- | --- | --- |
| Multi-file gathering | xong | `gather.py` |
| Cây phân cấp mỗi version | xong | `hierarchy.py` |
| Leaf sentence / formula / figure | xong | `hierarchy.py` |
| Không tách sai viết tắt, URL, số thập phân, toán | xong | `split_sentences` |
| List = cha, `\item` = con | xong | `hierarchy.py` |
| Acknowledgements + Appendix | xong | `hierarchy.py` |
| References không vào cây | xong | skip heading + `thebibliography` |
| Version empty M1 vẫn ghi rõ | xong | `pipeline.parse_one_version` |
| Cleanup `\centering` / `[htbp]` / `\midrule` | chưa | `cleanup.py` |
| Unify math `$...$` / `equation` | chưa | `cleanup.py` |
| `\bibitem` → BibTeX | chưa | `bibitem.py` |
| Dedup nội dung + BibTeX across versions | chưa | `dedup.py` |
| Bảng HF `elements` / `hierarchy` / `bibtex` | chưa | local ID hiện là `vN#nK` |


---

## 2. Dữ liệu M1 và định dạng đầu vào

Parser không crawl arXiv. Nó đọc corpus M1 theo cấu trúc:

```text
data/working/{folder}/
  paper.json                 # bắt buộc nếu muốn CLI tự liệt kê paper
  v1/sources/*.tex           # nguồn thật
  v2/empty.json              # version không có TeX
```

`folder` có dạng:

- `2310-12345` → folder `2310-12345`
- `hep-th/9901001` → folder cũ theo cách `hep-th_9901001`

Version được xác định bằng folder `vN` (`v1`, `v2`, ...), không dựa vào tên file. 

| Tình huống version | Kết quả |
| --- | --- |
| Có `vN/empty.json` | `empty=true`, reason `empty record from M1` |
| Không có `vN/sources/` | `empty=true`, reason `missing sources directory` |
| Có sources nhưng không `\documentclass` | `empty=true`, reason `no \documentclass root` |
| Có root TeX | `empty=false`, ghi cây |

Có 3 cách dùng data:

1. Tự chạy M1: `python -m src.m1_crawling.run_m1 --ids assigned_ids.txt`
2. Nhận `data/working` từ người crawl / checkpoint
3. Nếu chưa có M1: chạy pytest + corpus giả ở mục 4

---

## 3. Setup chi tiết

### 3.1. Python

Repo yêu cầu Python 3.10+. Dev hiện tại chạy được 3.12.

```bash
python3 --version
cd /đường/dẫn/arXir_project
```

### 3.2. Virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r src/requirements.txt
python -m pip install pytest
```

`src/requirements.txt` có `bibtexparser`, nhưng phần raw tree không cần import nó. Pytest không nằm trong requirements nên phải cài riêng.

### 3.3. `PYTHONPATH`

Package là `src.*`, repo chưa cài editable. Mọi lệnh phải chạy từ root repo:

```bash
export PYTHONPATH=.
# hoặc: PYTHONPATH=. python -m ...
```

### 3.4. Data không commit

`data/` không đưa lên git. Output parse nằm ở:

- `data/working/.../parsed/`
- `data/tables/`

---

## 4. Test trước khi chạm corpus thật

### 4.1. Chạy file test

```bash
cd /đường/dẫn/arXir_project
export PYTHONPATH=.
python -m pytest tests/test_m2_hierarchy.py -q
```

Kỳ vọng:

```text
..............                                                           [100%]
14 passed in 0.xxs
```

Chạy verbose:

```bash
python -m pytest tests/test_m2_hierarchy.py -v
```

Chạy 1 test:

```bash
python -m pytest tests/test_m2_hierarchy.py::test_split_sentences_protects_abbreviation_url_math_decimal -v
```

### 4.2. Test nào cover cái gì

| Test | Nội dung |
| --- | --- |
| `test_strip_comments_keeps_escaped_percent` | `\%` không bị xóa như comment |
| `test_commented_include_is_ignored` | `% \input{...}` không follow; `\includegraphics` ≠ `\include` |
| `test_find_root_and_unused_files` | root `main.tex`, unused không vào cây |
| `test_multiple_documentclass_prefers_main` | heuristic chọn `main.tex` |
| `test_heading_helpers` | level section/subsection; nhận References / Acknowledgements / Appendix |
| `test_split_sentences_protects_abbreviation_url_math_decimal` | `i.e.` `Fig. 1` `et al.` URL `3.14` `$a.b$` |
| `test_parse_structure_lists_math_figure_table_ack_appendix` | equation, figure, table=figure, itemize, ack, appendix; References biến mất |
| `test_empty_tex_still_has_document_root` | TeX rỗng vẫn có node document |
| `test_ieee_and_chapter_styles` | IEEEtran vs memoir (chapter) |
| `test_parse_one_version_pipeline` | CLI logic: v1 có TeX, v2 empty.json |
| `test_two_versions_different_trees` | cùng câu, khác heading => hai cây |
| `test_unbraced_and_nested_includes` | `\input body` + `chapters/methods.tex` |
| `test_thebibliography_and_appendix_switch_excluded_from_tree` | `\appendix` + skip bib |
| `test_display_brackets_and_align` | `\[...\]` và `align` |

Pytest tạo thư mục tạm (`tmp_path`), nên không chạm `data/working` của bạn.

### 4.3. Dry-run trên corpus giả

Tạo paper mini rồi dùng đúng CLI production:

```bash
cd /đường/dẫn/arXir_project
export PYTHONPATH=.
mkdir -p /tmp/m2_demo/2310-12345/v1/sources
mkdir -p /tmp/m2_demo/2310-12345/v2

cat > /tmp/m2_demo/2310-12345/paper.json << 'EOF'
{"arxiv_id": "2310.12345", "title": "Demo"}
EOF

cat > /tmp/m2_demo/2310-12345/v1/sources/main.tex << 'EOF'
\documentclass{article}
\title{Demo Paper}
\begin{document}
\section{Introduction}
We study parsing. It works well.
\section*{Acknowledgements}
We thank colleagues.
\section{References}
Must not appear.
\end{document}
EOF

cat > /tmp/m2_demo/2310-12345/v2/empty.json << 'EOF'
{"empty": true, "reason": "pdf"}
EOF

python -m src.m2_parsing.run_m2 --working-dir /tmp/m2_demo --arxiv-id 2310.12345 -v
```

Kỳ vọng stdout dạng:

```text
Parsed 1 publications, 2 versions (1 with TeX, 1 empty). Trees: {working}/{id}/parsed/raw/vN/
```

Kiểm tra output:

```bash
ls /tmp/m2_demo/2310-12345/parsed/raw/v1/
# tree.json  nodes.jsonl  edges.jsonl  meta.json

python3 - << 'PY'
import json
from pathlib import Path

tree = json.loads(Path('/tmp/m2_demo/2310-12345/parsed/raw/v1/tree.json').read_text())
print('root kind:', tree['kind'], 'title:', tree['content'])
print('child kinds:', [c['kind'] for c in tree['children']])
print('headings:', [c['content'] for c in tree['children'] if c['kind'] in ('heading','acknowledgement')])
PY
```

Kỳ vọng: có Introduction + Acknowledgements, không có References.

`meta.json` cho version 2 phải có `"empty": true`.

Lưu ý: dù `--working-dir` là `/tmp/m2_demo`, file tổng hợp vẫn ghi vào repo:

```text
data/tables/raw_parse_index.json
data/tables/raw_nodes.jsonl
data/tables/raw_edges.jsonl
data/tables/metrics_m2_raw.json
```

(`src/common/config.py`: `TABLES_DIR = data/tables`, không theo `--working-dir`.)

---

## 5. Chạy trên corpus M1 thật

### 5.1. Kiểm tra corpus trước

```bash
ls data/working | head
# ví dụ: 2310-12345

ls data/working/2310-12345
# paper.json   v1/   v2/   ...

ls data/working/2310-12345/v1/sources | head
# *.tex  *.bib
```

Nếu `data/working` rỗng: M1 chưa chạy, hoặc data nằm chỗ khác -> dùng `--working-dir`.

### 5.2. Một paper

```bash
export PYTHONPATH=.
python -m src.m2_parsing.run_m2 --working-dir data/working --arxiv-id 2310.12345 -v
```

`--arxiv-id` có thể lặp:

```bash
python -m src.m2_parsing.run_m2 --arxiv-id 2310.12345 --arxiv-id 2310.99999
```

### 5.3. Cả corpus

```bash
export PYTHONPATH=.
python -m src.m2_parsing.run_m2 --working-dir data/working
```

CLI sẽ tự liệt kê folder có `paper.json` (hoặc đoán id từ tên folder).

Exit code:

| Code | Ý nghĩa |
| --- | --- |
| `0` | Có ít nhất 1 publication được xét, kể cả empty |
| `1` | Không tìm thấy publication nào |

### 5.4. Không gọi `run_milestone2()`

```python
from src.m2_parsing.pipeline import run_milestone2
run_milestone2()  # ghi cây raw rồi raise NotImplementedError
```

Hàm đó dành cho M2 hoàn chỉnh (cleanup + dedup). CLI `run_m2` chỉ gọi `run_raw_hierarchy()`.

---

## 6. Output và cách đọc

### 6.1. Cây từng version

Với `2310.12345` v1:

```text
data/working/2310-12345/parsed/raw/v1/tree.json
data/working/2310-12345/parsed/raw/v1/nodes.jsonl
data/working/2310-12345/parsed/raw/v1/edges.jsonl
data/working/2310-12345/parsed/raw/v1/meta.json
data/working/2310-12345/parsed/raw/index.json
```

`tree.json` rút gọn:

```json
{
  "kind": "document",
  "content": "Demo Paper",
  "source_hint": "document",
  "children": [
    {
      "kind": "heading",
      "content": "Introduction",
      "children": [
        {
          "kind": "paragraph",
          "children": [
            { "kind": "sentence", "content": "We study parsing." }
          ]
        }
      ]
    }
  ]
}
```

`nodes.jsonl`: mỗi dòng là một node JSON.

```json
{"local_id": "v1#n0", "kind": "document", "content": "Demo Paper", "source_hint": "document"}
{"local_id": "v1#n1", "kind": "heading", "content": "Introduction", "source_hint": "section:Introduction"}
```

`edges.jsonl`: một hàng = một cạnh con → cha. Root không có parent.

```json
{"parent_id": "v1#n0", "child_id": "v1#n1", "version": 1}
```

`local_id = v{version}#n{preorder_index}`. Chưa phải `element_id` HF (`2310-12345#s1`).

`meta.json`:

```json
{
  "arxiv_id": "2310.12345",
  "version": 1,
  "empty": false,
  "reason": "",
  "n_nodes": 12,
  "n_edges": 11,
  "compilation_files": ["main.tex", "intro.tex"],
  "unused_files": ["unused.tex"],
  "normalized": false
}
```

`normalized: false` nghĩa là chưa cleanup. Người làm bước sau không được giả định text đã được rửa.

### 6.2. Bảng tổng hợp

```text
data/tables/raw_parse_index.json
data/tables/raw_nodes.jsonl
data/tables/raw_edges.jsonl
data/tables/metrics_m2_raw.json
```

`metrics_m2_raw.json` (cây raw) có các key như:

| Key | Ý nghĩa |
| --- | --- |
| `n_publications` | số folder paper |
| `n_versions_total` / `n_versions_parsed` / `n_versions_empty` | coverage |
| `version_success_rate` | parsed / total |
| `n_nodes_before_dedup` / `n_edges_before_dedup` | kích thước cây thô |
| `n_compilation_files` / `n_unused_tex_files` | gathering |
| `kind_counts` | phân bố `sentence`, `heading`, … |
| `n_elements_after_dedup` / `n_bib_*` | null cho tới khi có dedup |
| `output_bytes` | dung lượng `parsed/raw` + bảng raw |

Xem JSON:

```bash
python3 -m json.tool data/tables/metrics_m2_raw.json
```

---

## 7. Thiết kế kỹ thuật

```text
vN/sources/*.tex
        │
        ▼
 gather.py
   find_document_root
   compilation_path          # DFS, unique
   concatenate_compilation_tex
        │
        ▼
 hierarchy.py
   parse_tex_to_tree → ParseNode
   nodes_and_edges → local_id + cạnh
        │
        ▼
 pipeline.py  parse_one_version / run_raw_hierarchy
        │
        ▼
 parsed/raw/vN/  +  data/tables/raw_*.jsonl
```

### 7.1. Gathering

- Root là `.tex` có `\documentclass` và không nằm trong comment `%`.
- Nếu 0 candidate → empty. Nếu nhiều candidate → ưu tiên `main`, `paper`, `manuscript`, `article`, `root`, `ms`.
- Regex `\input` / `\include` phải tránh match `\includegraphics`, `\inputenc`.
- Comment `%` không bị escape, `\%` được giữ.
- Resolve path: thư mục file hiện tại, rồi `sources/`; tự thêm `.tex` nếu thiếu.
- File không nằm trên compilation path được coi là auxiliary, không parse.

### 7.2. Cây

`ParseNode(kind, content, children, source_hint)`.

| kind | Khi nào |
| --- | --- |
| `document` | root; `content` = `\title` nếu có |
| `heading` | `\part` … `\subparagraph`, kể cả `*` |
| `acknowledgement` | heading Acknowledgements / Thanks |
| `appendix` | heading Appendix… hoặc sau `\appendix` |
| `paragraph` | prose giữa hai empty line |
| `sentence` | leaf văn xuôi |
| `formula` | `equation` / `align` / `$$` / `\[...\]` / … |
| `figure` | figure + table/tabular/longtable |
| `list` / `list_item` | itemize / enumerate / description |

Mức heading tự suy theo tên lệnh:

`part=1, chapter=2, section=3, subsection=4, subsubsection=5, paragraph=6, subparagraph=7`

Stack logic: heading mới pop khi level ≥ node đỉnh. Không hardcode kiểu section cho IEEE hoặc book. 

Chỉ parse phần trong `\begin{document} ... \end{document}` nếu có.

### 7.3. Tách câu

Tách `. ? !` nhưng không tách ở các trường hợp:

- đang trong `$...$` hoặc `\(...\)`
- đang trong argument `{...}` của lệnh
- viết tắt: `i.e.` `e.g.` `et al.` `Fig.` `Eq.` `Dr.`
- `Fig. 1`
- `3.14`
- URL / email
- `file.tex` (chữ + `.` + chữ, không có khoảng trắng)

Cụm `holds. Next` thì phải tách, vì đó là câu mới.

### 7.4. Tránh nhầm vùng

- `\section{References}` / `Bibliography` → bỏ subtree tới heading cùng hoặc cao hơn.
- `thebibliography`, `\bibliography` → skip.
- Acknowledgements và Appendix vẫn phải có trong cây.

---

## 8. API cho người làm bước sau

```python
from pathlib import Path
from src.m2_parsing.pipeline import parse_one_version, run_raw_hierarchy
from src.m2_parsing.hierarchy import parse_tex_to_tree, nodes_and_edges

result = parse_one_version("2310.12345", 1, working_dir=Path("data/working"))
assert result.tree.kind == "document"
print(result.n_nodes, result.compilation_files, result.empty)

# hoặc parse trực tiếp TeX đã ghép sẵn
text = open("paper.tex", encoding="utf-8").read()
tree = parse_tex_to_tree(text)
nodes, edges = nodes_and_edges(tree, version=1)
```

Nối tiếp M2 trong các bước sau:

1. Cleanup từng node (`cleanup.py`) rồi so `kind + content` giữa các version (`dedup.py`).
2. `element_id = {folder}#{s1|h1|root1|…}`; cùng content thì cùng id.
3. `\bibitem` / `.bib` → union field, canonical `\cite`.
4. Ghi `elements.jsonl`, `hierarchy.jsonl`, `bibtex.json` theo `src/common/schemas.py`.

Không parse lại TeX nếu đã có `parsed/raw/` rồi, trừ khi đổi `gather.py` / `hierarchy.py`.

---

## 9. Troubleshooting

| Hiện tượng | Nguyên nhân / cách xử |
| --- | --- |
| `No module named pytest` | `python -m pip install pytest` trong venv |
| `No module named src` | chạy từ root repo, `export PYTHONPATH=.` |
| `Parsed 0 publications` + exit 1 | `--working-dir` sai, chưa có `paper.json`, hoặc chưa chạy M1 |
| Tất cả version empty, reason `missing sources directory` | M1 chưa extract `.tex` vào `vN/sources` |
| reason `no \documentclass root` | PDF-only hoặc `\documentclass` nằm trong comment |
| Cây thiếu chương | file nằm ngoài compilation path, xem `meta.json` -> `unused_files` |
| References vẫn ở trong cây | tiêu đề không nằm trong từ điển (`References`, `Bibliography`, …) - bổ sung `_REF_TITLES` |
| Tách câu sai ở URL / `i.e.` | sửa `split_sentences` + thêm case vào test |
| `run_milestone2` raise | đúng thiết kế; dùng `python -m src.m2_parsing.run_m2` |
| Bảng raw không ở cạnh `--working-dir` | luôn ghi vào `data/tables/` theo `config.TABLES_DIR` |

Log thiếu include:

```bash
python -m src.m2_parsing.run_m2 --working-dir data/working --arxiv-id 2310.12345 -v
# WARNING src.m2_parsing.gather: Missing include 'foo' from ...
```

---

## 10. Giới hạn có chủ ý

1. Nội dung còn chứa lệnh format (`\centering`, `[ht]`). Đây là “pre-cleanup”, không phải output final.
2. Cùng câu ở v1 và v2 vẫn là hai `local_id` khác nhau cho tới phase dedup.
3. Không phải TeX engine: `\def\mysection{...}` không tự thành heading; `\input` trong `\iffalse` vẫn follow nếu không comment `%`.
4. `.sty` / `.cls` không nằm trên `\input` thì không parse.

---

## 11. File liên quan

| Path | Vai trò |
| --- | --- |
| `src/m2_parsing/gather.py` | root, include, concat |
| `src/m2_parsing/hierarchy.py` | scanner cây + tách câu |
| `src/m2_parsing/pipeline.py` | `parse_one_version`, `run_raw_hierarchy`, ghi disk |
| `src/m2_parsing/run_m2.py` | CLI |
| `src/m2_parsing/analyze.py` | `metrics_m2_raw.json` |
| `tests/test_m2_hierarchy.py` | 14 unit/integration test |
| `src/m2_parsing/cleanup.py` | stub — bước sau |
| `src/m2_parsing/bibitem.py` | stub — bước sau |
| `src/m2_parsing/dedup.py` | stub — bước sau |

Skeleton M2 đầy đủ nằm ở `src/m2_parsing/README.md`.

---

## 12. Ghi chú ngắn cho team

- Đây là phần raw, không phải output final.
- Mục tiêu là cây đúng về cấu trúc trước khi “rửa” text.
- Nếu thấy file `unused_files` nhiều, kiểm tra lại path compile và `\input`/`\include`.
- Nếu `References` vẫn nằm trong cây, sửa regex / danh sách tiêu đề chứ không nên lạm dụng hardcode.
- Khi tới bước cleanup/dedup, đừng lấy `tree.json` raw làm final; phải qua bước chuẩn hóa và canonical ID.

Nói ngắn gọn: M2 raw hierarchy đã đi đúng hướng, và phần còn lại chỉ là `rửa chữ + gắn ID + dedup`.
