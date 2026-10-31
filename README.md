# arXiv Project (HCMUS Intro-DS)

Group skeleton for the three milestones in
<https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/>.

M1 (crawl), M2 (parse) and M3 (matching) are implemented under `src/`; the
column names in `src/common/schemas.py` follow the lab book and must not change
unless the lab book changes.

| Milestone | Goal | Hugging Face tables |
| --- | --- | --- |
| M1 | Resolve assigned arXiv IDs, every version’s `.tex`/`.bib`, Semantic Scholar refs | `papers`, `references` |
| M2 | Compilation path, hierarchy, cleanup, BibTeX, dedup across versions | `elements`, `hierarchy`, `bibtex` |
| M3 | Clean, label, features, model, **MRR@5**, publish Parquet | `predictions` (+ export of all six) |

## Environment

Python **3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r src/requirements.txt
```

Optional: Semantic Scholar API key in `S2_API_KEY` (steadier than the shared unauthenticated pool).

Do **not** commit `data/`, `assigned_ids.txt`, or API keys.

## Assigned IDs

Lab Instructors provide the ID range. Put one canonical arXiv ID per line in
`assigned_ids.txt` (UTF-8). Blank lines and `#` comments are ignored. See
`assigned_ids.example.txt`.

## How to run

```bash
# M1 — crawl assigned papers (export.arxiv.org only, ≥ 3 s between calls)
python -m src.m1_crawling.run_m1 --ids assigned_ids.txt

# M1 batch flow (Colab): crawl one assigned range, then references + tables
python -m src.m1_crawling.run_arxiv_only --range 5 --batch-size 200
python -m src.m1_crawling.run_m1_all --range 5 --data-dir data

# M2 — parse every publication produced by M1
python -m src.m2_parsing.run_m2

# M3 — matching + local Hugging Face export
python -m src.m3_matching.run_m3
```

Working data (suggested):

```text
data/working/{2310-12345}/     # M1 sources + metadata + S2 refs
data/working/{2310-12345}/parsed/   # M2 elements / hierarchy / bibtex
data/labels/{arxiv_id}.jsonl   # M3 ground truth (manual + auto)
data/tables/                   # jsonl + metrics_*.json
data/hf_dataset/               # 6 Parquet configs + dataset card
```

## Hướng dẫn chi tiết theo milestone (đọc file này)

Thành viên **không cần đọc hết repo**: mở đúng README của việc mình nhận, làm theo checklist.

| Việc | File hướng dẫn |
| --- | --- |
| Utils dùng chung (làm trước) | [`src/common/README.md`](src/common/README.md) |
| Milestone 1 — crawl | [`src/m1_crawling/README.md`](src/m1_crawling/README.md) |
| Milestone 2 — parse / dedup | [`src/m2_parsing/README.md`](src/m2_parsing/README.md) |
| Milestone 3 — matching + HF | [`src/m3_matching/README.md`](src/m3_matching/README.md) |

Mỗi file ghi: mục tiêu, thứ tự code, **từng hàm phải viết gì**, output trên đĩa, và checklist “xong khi nào”. Trong code, chỗ `TODO(M1/M2/M3)` trùng với README đó.

## Who implements what

| Path | Fill in |
| --- | --- |
| `src/common/` | IDs, HTTP retry, JSONL/Parquet I/O, RAM/time metrics |
| `src/m1_crawling/discover.py` | arXiv API `id_list` → metadata + version count |
| `src/m1_crawling/download.py` | `https://export.arxiv.org/src/{id}vN`, extract `.tex`/`.bib` only |
| `src/m1_crawling/semantic_scholar.py` | Graph API references; keep old `hep-th/9901001` IDs |
| `src/m1_crawling/pipeline.py` | End-to-end crawl + empty records for PDF-only versions |
| `src/m2_parsing/gather.py` | `\documentclass` root, `\input`/`\include` path |
| `src/m2_parsing/hierarchy.py` | Tree; sentence / block math / figure leaves; skip References |
| `src/m2_parsing/cleanup.py` | Drop non-semantic cmds; unify `$...$` and `equation` |
| `src/m2_parsing/bibitem.py` | `\bibitem` → BibTeX |
| `src/m2_parsing/dedup.py` | Union BibTeX fields + shared `element_id` across versions |
| `src/m3_matching/labelling.py` | ≥5 manual papers (≥20 entries each, ≥100 total); auto ≥10% of the rest |
| `src/m3_matching/features.py` | Pair features (hierarchy allowed); document each in the poster |
| `src/m3_matching/split.py` | test/valid = 1 manual + 1 auto each; train = remainder |
| `src/m3_matching/model.py` | `m×n` candidate matrix, top-5 list |
| `src/m3_matching/evaluate.py` | MRR@5 on test |
| `src/m3_matching/export_hf.py` | Sharded Parquet + YAML dataset card, **no** custom load script |

Column schemas live in `src/common/schemas.py` (must stay flat: one-level string lists only).

## Constraints copied from the lab book

- Crawl **assigned IDs only**, every version `v1..vN`. Do not harvest all of arXiv.
- Use `export.arxiv.org`, never `arxiv.org` (403 / robot block).
- Extract `.tex` and `.bib`; do not edit figure commands inside TeX.
- PDF-only / non-TeX versions: **empty record**, do not drop the paper.
- `references` table: rows **with an arXiv ID only**. Local JSON keeps all S2 refs.
- Reports (M1/M2) are a **separate** Jupyter Book repo; figures generated at compile time.
- Benchmark: Google Colab CPU-only; measure wall time and RAM (`psutil` / `time -v`).

## Label file format (M3)

`data/labels/{arxiv_id}.jsonl`:

```json
{"citation_key": "vaswani2017", "groundtruth_arxiv_id": "1706.03762", "source": "manual"}
{"citation_key": "unknownBook", "groundtruth_arxiv_id": null, "source": "auto"}
```

`source` is `manual` or `auto`. One true reference per entry, or `null` when none of the crawled refs match.
