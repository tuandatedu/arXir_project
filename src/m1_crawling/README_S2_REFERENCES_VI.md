# M1 â€” Semantic Scholar references + 2 báº£ng papers/references (cĂ¡ch cháº¡y)

> **ÄĂ¢y lĂ  "pháº§n cá»§a ngÆ°á»i 2"**: crawl references qua Semantic Scholar, xuáº¥t 2 báº£ng
> `papers` / `references` + validate, vĂ  pipeline M1 Ä‘áº§y Ä‘á»§.
> Crawler arXiv (táº£i source `.tex`/`.bib` hĂ ng loáº¡t) lĂ  pháº§n cá»§a ngÆ°á»i 1 â€”
> xem [`README_ARXIV_CRAWLER.md`](README_ARXIV_CRAWLER.md) vĂ  [`README_CONCURRENT_VI.md`](README_CONCURRENT_VI.md).

Nguá»“n yĂªu cáº§u: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/>

## 1. File thuá»™c trĂ¡ch nhiá»‡m pháº§n nĂ y

| File | Vai trĂ² |
|---|---|
| `semantic_scholar.py` | Gá»i S2 Graph API láº¥y references cá»§a 1 publication; chuáº©n hĂ³a record local; pacing/cooldown + validate payload |
| `s2_batch.py` | Batch runner dĂ¹ng chung cho notebook: resume cache, validate payload, tá»•ng há»£p metrics theo publication |
| `tables.py` | Xuáº¥t `papers.json` + `references.json` (cá»™t pháº³ng); `validate_m1_tables` |
| `pipeline.py` | Ná»‘i táº¥t cáº£: discover â†’ download má»i version â†’ S2 â†’ tables + metrics |
| `run_m1.py` | CLI end-to-end: `--ids`, `--semantic-scholar-api-key`, `--output` |
| `corpus.py` | Ghi working folder (`paper.json`, `vN/sources/`, `references_s2.json`) |
| `analyze.py` | Sá»‘ liá»‡u corpus (success rate, kĂ­ch thÆ°á»›c, ref coverage) â†’ `metrics_m1.json` |
| `src/common/{ids,io,metrics,rate_limit}.py` | Helpers dĂ¹ng chung (normalize ID, JSONL/JSON, track_run, retry/delay) |
| `colab_s2_references.ipynb` | Notebook Colab production: Ä‘á»c checkpoint ngÆ°á»i 1 â†’ crawl S2 (resume) â†’ xuáº¥t báº£ng |
| `tests/test_m1_pipeline.py` | Test OFFLINE (mock network), khĂ´ng gá»i arXiv / S2 tháº­t |
| `tests/test_m1_batch.py` | Test OFFLINE batch runner: payload rá»—ng/thiáº¿u/sai kiá»ƒu, cache, resume, pacing |

Pháº§n nĂ y **khĂ´ng** Ä‘á»•i CLI crawler `run_arxiv_only.py` cá»§a ngÆ°á»i 1.

## 2. Tiá»n Ä‘á»

1. NgÆ°á»i 1 Ä‘Ă£ crawl (hoáº·c Ä‘ang crawl) vĂ  cĂ³ checkpoint `batch_*.tar.gz` + `batch_*.json`
   trĂªn Google Drive cho range cá»§a báº¡n.
2. Code trĂªn nhĂ¡nh cá»§a nhĂ³m (máº·c Ä‘á»‹nh `M1-Update-pipeline`) Ä‘Ă£ Ä‘Æ°á»£c push; notebook sáº½ `git pull` nhĂ¡nh Ä‘Ă³.
3. (Khuyáº¿n nghá»‹) API key Semantic Scholar â€” khĂ´ng cĂ³ váº«n cháº¡y Ä‘Æ°á»£c nhÆ°ng dá»… 429 hÆ¡n.

```text
Unauthenticated S2: ~1 request/s vĂ  100 request / 5 phĂºt.
CĂ³ key: á»•n Ä‘á»‹nh hÆ¡n. Key Ä‘áº·t trong env S2_API_KEY hoáº·c Secrets cá»§a Colab.
```

## 3. CĂ i Ä‘áº·t & test offline (mĂ¡y Windows / VS Code)

Tá»« thÆ° má»¥c gá»‘c repository:

```bash
python -m pip install -r src/requirements.txt
python -m pytest -q tests/test_m1_pipeline.py
```

Test mock toĂ n bá»™ network (S2, table write, pipeline end-to-end) â€” khĂ´ng spam API.
Náº¿u cháº¡y crawler ngÆ°á»i 1 trĂªn mĂ¡y thĂ¬ cĂ i `requirements-crawler.txt`; pháº§n nĂ y cáº§n
Ä‘áº§y Ä‘á»§ `src/requirements.txt` (arxiv, requests, psutil, pandasâ€¦).

Cháº¡y riĂªng test payload vĂ  bá»™ Ä‘iá»u tiáº¿t request:

```powershell
python -m pytest -q tests/test_m1_pipeline.py -k "payload_validation_and_pacing"
python -m pytest -q tests/test_m1_batch.py
```

Test nĂ y kiá»ƒm tra `references=[]` há»£p lá»‡, payload thiáº¿u/sai kiá»ƒu
`references`, vĂ  viá»‡c request Ä‘i qua bá»™ Ä‘iá»u tiáº¿t trÆ°á»›c má»—i attempt.
`test_m1_batch.py` kiá»ƒm tra thĂªm cache/resume, tráº¡ng thĂ¡i `invalid_id`, vĂ 
viá»‡c payload lá»—i khĂ´ng táº¡o cache thĂ nh cĂ´ng.

## 4. CĂ¡ch cháº¡y A â€” Colab trĂªn checkpoint Drive cá»§a ngÆ°á»i 1 (production)

Notebook: `src/m1_crawling/colab_s2_references.ipynb`. Cháº¡y **sau** notebook crawl
`M1_Colab_Concurrent_Limited.ipynb` / `colab_shared_crawler.ipynb` cá»§a ngÆ°á»i 1.
Quy trĂ¬nh: GitHub branch â†’ Drive â†’ Ä‘á»c ID tá»« checkpoint â†’ crawl references (resume)
â†’ xuáº¥t 2 báº£ng + validate.

### 4.1. SET UP â€” clone branch vĂ  cĂ i thÆ° viá»‡n

- Cell SET UP Ä‘áº§u tiĂªn clone nhĂ¡nh `BRANCH` (máº·c Ä‘á»‹nh `M1-Update-pipeline`) tá»« `REPO_URL` cá»§a nhĂ³m.
  Náº¿u Ä‘Ă£ clone rá»“i thĂ¬ `fetch` + `checkout` + `pull --ff-only`.
- CĂ i `src/requirements.txt`, rá»“i cháº¡y `pytest tests/test_m1_pipeline.py` ngay trong Colab
  Ä‘á»ƒ cháº¯c code khá»›p nhĂ¡nh má»›i nháº¥t.

### 4.2. Mount Google Drive

```python
from google.colab import drive
drive.mount("/content/drive")
```

### 4.3. Trá» Ä‘Ăºng thÆ° má»¥c Drive cá»§a range

`RANGE_ID` vĂ  `DATA_DIR` pháº£i **trĂ¹ng vá»›i notebook crawl cá»§a ngÆ°á»i 1** Ä‘á»ƒ tĂ¬m Ä‘Æ°á»£c checkpoint:

```python
RANGE_ID = 4             # range cá»§a ngÆ°á»i cháº¡y (1..5)
DATA_DIR = Path(f"/content/drive/MyDrive/arxiv-project-data/m1/range_{RANGE_ID}_dev")
```

Cell assert sáº½ bĂ¡o lá»—i náº¿u chÆ°a cĂ³ `batch_*.json` â€” tá»©c lĂ  pháº£i cháº¡y crawl ngÆ°á»i 1 trÆ°á»›c.
Notebook **chá»‰ Ä‘á»c** checkpoint cá»§a ngÆ°á»i 1; dá»¯ liá»‡u S2 ghi vĂ o thÆ° má»¥c riĂªng
`MY_REFS_DIR = /content/drive/MyDrive/references/range_{RANGE_ID}`:

```text
DATA_DIR/                                # checkpoint ngÆ°á»i 1 (chá»‰ Ä‘á»c)
  batch_00000.tar.gz + .json
MY_REFS_DIR/
  reference/2307-00001.json              # Má»ŒI ref Ä‘Ă£ crawl (resume táº¡i Ä‘Ă¢y, tĂªn pháº³ng)
  tables/papers.json
  tables/references.json
  tables/metrics_s2_references.json
  tables/s2_crawl_records.csv
  tables/validation_report.json
```

### 4.4. Náº¡p S2_API_KEY

Äáº·t env `S2_API_KEY` trong notebook (hoáº·c add secret cá»§a Colab rá»“i Ä‘á»c vĂ o env).
**KhĂ´ng commit key vĂ o repo** â€” náº¿u key Ä‘Ă£ lá»¡ náº±m trong notebook thĂ¬ xoĂ¡ cell
hardcode, rotate key trĂªn S2, vĂ  chá»‰ giá»¯ env/Secrets.

### 4.5. Äá»c danh sĂ¡ch paper tá»« checkpoint

Má»—i `batch_*.tar.gz` chá»©a `papers.jsonl` (metadata ngÆ°á»i 1 Ä‘Ă£ crawl). Cell loader:

- Ä‘á»c `papers.jsonl` tá»« má»i `batch_*.tgz`/`batch_*.json` tĂ¬m tháº¥y;
- giá»¯ **má»i** paper cĂ³ metadata, khĂ´ng lá»c theo tráº¡ng thĂ¡i táº£i TeX (bĂ i chá»‰ cĂ³ PDF váº«n lĂ  má»™t hĂ ng cá»§a báº£ng `papers`);
- dedupe theo `arxiv_id`; bĂ¡o riĂªng sá»‘ ID Ä‘á» giao cĂ²n thiáº¿u so vá»›i checkpoint.

Notebook Ä‘á»c API key tá»« `S2_API_KEY` (env) hoáº·c Colab Secrets rá»“i truyá»n tháº³ng
`api_key=` vĂ o batch runner; khĂ´ng Ä‘áº·t key trá»±c tiáº¿p trong notebook. Luá»“ng request
dĂ¹ng chung bá»™ pacing/cooldown cá»§a `semantic_scholar.py`, bao gá»“m cáº£ cĂ¡c láº§n retry.

### 4.6. Crawl references (resume, cĂ³ Ä‘o runtime)

Má»—i paper: `run_s2_batch` gá»i `fetch_s2_payload_with_status` â†’
`s2_ref_to_local_record` â†’ ghi `MY_REFS_DIR/reference/<folder>.json`.

- **1 request / publication** (S2 khĂ´ng phĂ¢n version), delay/cooldown do
  `S2_MIN_DELAY_SEC` / `S2_429_COOLDOWN_SEC` trong library lo, Ă¡p dá»¥ng cho cáº£ retry.
- **Resume**: paper Ä‘Ă£ cĂ³ cache há»£p lá»‡ â†’ `from_cache = true`, khĂ´ng gá»i API láº¡i.
  Run bá»‹ ngáº¯t thĂ¬ má»Ÿ láº¡i session, mount Drive, cháº¡y láº¡i cell lĂ  tiáº¿p tá»¥c.
- Lá»—i tá»«ng paper (`not_indexed` 404, `failed` sau retry, `invalid_id`) Ä‘Æ°á»£c log rá»“i
  bá» qua, khĂ´ng dá»«ng cáº£ run.
- Progress in má»—i 50 paper; cuá»‘i run in sá»‘ `n_zero_refs` / `n_api_errors` /
  `n_processing_errors` / `n_cache_hits`.
- Pháº£n há»“i HTTP 200 chá»‰ Ä‘Æ°á»£c ghi cache khi payload cĂ³ trÆ°á»ng `references` kiá»ƒu
  list. `references: []` lĂ  káº¿t quáº£ `ok` há»£p lá»‡; thiáº¿u trÆ°á»ng hoáº·c sai kiá»ƒu lĂ 
  `failed`. Pháº§n tá»­ reference khĂ´ng pháº£i object cÅ©ng Ä‘Æ°á»£c ghi nháº­n lĂ  lá»—i vĂ 
  khĂ´ng ghi cache Ä‘á»ƒ trĂ¡nh máº¥t dá»¯ liá»‡u Ă¢m tháº§m.
- Cache khĂ´ng pháº£i list cĂ¡c object bá»‹ coi lĂ  há»ng vĂ  Ä‘Æ°á»£c crawl láº¡i.

### 4.7. Recovery

Cháº¡y láº¡i cell crawl á»Ÿ má»¥c 4.6 lĂ  Ä‘á»§: paper Ä‘Ă£ lÆ°u sáº½ `from_cache`, paper lá»—i/chÆ°a tá»›i Ä‘Æ°á»£c thá»­ láº¡i.
Cell Recovery cĂ³ thĂªm bÆ°á»›c rĂ  cache rá»—ng: `find_empty_cache_ids()` liá»‡t kĂª cĂ¡c file
`[]` (cĂ³ thá»ƒ há»£p lá»‡ hoáº·c do code cÅ©). Chá»‰ Ä‘Æ°a cĂ¡c ID Ä‘Ă£ kiá»ƒm tra vĂ o
`run_s2_batch(..., force_recrawl_ids=[...])`; khĂ´ng xĂ³a toĂ n bá»™ cache.
Náº¿u 429 dá»“n dáº­p thĂ¬ chá» â‰¥ 5 phĂºt rá»“i cháº¡y láº¡i; **khĂ´ng tÄƒng tá»‘c hoáº·c má»Ÿ 2 notebook song song**
trĂªn cĂ¹ng `MY_REFS_DIR` / `TABLES_DIR`.

### 4.8. Xuáº¥t 2 báº£ng `papers` / `references` + validate

- `papers`: metadata Ä‘á»c tá»« checkpoint (1 hĂ ng / publication, cá»™t schema `PaperRow`).
- `references`: chá»‰ ref **cĂ³ arXiv ID** (matching pool cá»§a M3); má»i ref váº«n náº±m trong
  `MY_REFS_DIR/reference/<folder>.json`.
- `validate_m1_tables` kiá»ƒm tra thiáº¿u thĂ´ng tin / sai kiá»ƒu / trĂ¹ng láº·p, in ra vĂ  ghi vĂ o metrics.
- Ghi thĂªm `s2_crawl_records.csv` (log tá»«ng paper: arxiv_id, status, n_refs, n_arxiv,
  n_refs_without_arxiv, from_cache, elapsed_s, error_kind, error) Ä‘á»ƒ Ä‘á»‘i chiáº¿u / gá»­i ngÆ°á»i xá»­ lĂ½ dá»¯ liá»‡u.

### 4.9. BĂ n giao

Gá»­i cho ngÆ°á»i xá»­ lĂ½ dá»¯ liá»‡u / Ä‘áº©y lĂªn Hugging Face á»Ÿ M3:

- `MY_REFS_DIR/tables/papers.json`, `MY_REFS_DIR/tables/references.json`,
  `MY_REFS_DIR/tables/s2_crawl_records.csv`, `metrics_s2_references.json`,
  `validation_report.json`;
- thÆ° má»¥c `MY_REFS_DIR/reference/` trĂªn Drive (chá»©a **má»i** ref, ká»ƒ cáº£ ref khĂ´ng cĂ³ arXiv ID) â€”
  Ä‘á»«ng xĂ³a trÆ°á»›c khi submit M3.

## 5. CĂ¡ch cháº¡y B â€” pipeline Ä‘áº§y Ä‘á»§ trĂªn mĂ¡y (end-to-end)

Cháº¡y Ä‘Æ°á»£c cáº£ discover + download source + S2 references + tables trong **má»™t lá»‡nh**
(khi muá»‘n benchmark M1 Ä‘áº§y Ä‘á»§ hoáº·c test nhá» trĂªn mĂ¡y):

```bash
# env S2_API_KEY=xxx (Windows PowerShell: $env:S2_API_KEY="xxx")
python -m src.m1_crawling.run_m1 --ids assigned_ids.txt
```

TĂ¹y chá»n:

| Flag | Ă nghÄ©a |
|---|---|
| `--ids` (báº¯t buá»™c) | File UTF-8, 1 arXiv ID / dĂ²ng (xem `assigned_ids.example.txt`) |
| `--semantic-scholar-api-key` | Key S2; fallback env `S2_API_KEY` |
| `--output` | Working corpus dir (máº·c Ä‘á»‹nh `data/working`) |
| `--verbose` | DEBUG logging |

Pipeline tĂ´n trá»ng `ARXIV_MIN_DELAY_SEC` (3s) vĂ  `S2_MIN_DELAY_SEC` (1s), má»™t connection
táº¡i má»™t thá»i Ä‘iá»ƒm. **1 paper lá»—i thĂ¬ log rá»“i tiáº¿p tá»¥c**, khĂ´ng abort cáº£ list.

Output trĂªn Ä‘Ä©a:

```text
data/working/{2310-12345}/
  paper.json
  references_s2.json          # Má»ŒI ref (ká»ƒ cáº£ khĂ´ng cĂ³ arXiv ID)
  v1/sources/*.tex, *.bib
  v2/empty.json               # vĂ­ dá»¥ PDF-only
data/tables/papers.json
data/tables/references.json   # CHá»ˆ ref cĂ³ arXiv ID
data/tables/metrics_m1.json   # time + RAM + n_refs + validation
```

## 6. RĂ ng buá»™c / lÆ°u Ă½

- Báº£ng `references` CHá»ˆ giá»¯ ref cĂ³ arXiv ID; local corpus PHáº¢I giá»¯ Ä‘á»§ má»i ref.
- Ref khĂ´ng cĂ³ arXiv ID â†’ `ref_arxiv_id = null` á»Ÿ local, bá»‹ loáº¡i khi xuáº¥t báº£ng.
- Scheme cÅ© `hep-th/9901001` Ä‘Æ°á»£c giá»¯ nguyĂªn, khĂ´ng Ä‘á»•i sang dáº¡ng má»›i.
- KhĂ´ng cháº¡y 2 process/notebook cĂ¹ng ghi vĂ o má»™t `MY_REFS_DIR` / `TABLES_DIR`.
- KhĂ´ng commit `data/`, checkpoint Drive, hay API key.
- Benchmark cuá»‘i cá»§a Ä‘á» lĂ  M1 **toĂ n há»‡ thá»‘ng** trĂªn Colab CPU-only (gá»™p pháº§n ngÆ°á»i 1);
  sá»‘ liá»‡u trong notebook nĂ y lĂ  metric riĂªng pháº§n S2 references.

## 7. Checklist "xong khi nĂ o"

- [ ] `pytest tests/test_m1_pipeline.py` vĂ  `pytest tests/test_m1_batch.py` pass trĂªn nhĂ¡nh má»›i nháº¥t.
- [ ] Notebook Ä‘á»c Ä‘Æ°á»£c checkpoint cá»§a ngÆ°á»i 1 (Ä‘Ăºng range / `DATA_DIR`).
- [ ] Má»—i paper trong `papers_meta` cĂ³ `MY_REFS_DIR/reference/<folder>.json`
      (hoáº·c Ä‘Ă£ Ä‘Æ°á»£c log lĂ  `not_indexed` / `failed` / `invalid_id` cĂ³ lĂ½ do).
- [ ] `papers.json` 1 hĂ ng / paper; `references.json` chá»‰ ref cĂ³ arXiv ID.
- [ ] `validate_m1_tables` ra `ok = True` (hoáº·c Ä‘Ă£ giáº£i thĂ­ch má»i issue trong metrics).
- [ ] `s2_crawl_records.csv` Ä‘á»§ Ä‘á»ƒ Ä‘á»‘i chiáº¿u `from_cache` / `ok` / `failed` / `not_indexed` / `invalid_id`.
- [ ] BĂ n giao `papers.json`, `references.json`, `MY_REFS_DIR/reference/` cho ngÆ°á»i xá»­ lĂ½ dá»¯ liá»‡u.
- [ ] KhĂ´ng cĂ²n API key nĂ o bá»‹ commit vĂ o repo.
