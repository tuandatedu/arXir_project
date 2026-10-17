# arXiv Milestone 1: Data Crawling

This repository contains the source code for crawling the arXiv IDs assigned by the Lab Instructors. It resolves every version, keeps only `.tex` and `.bib` files from source archives, and retrieves reference metadata from Semantic Scholar. It does not harvest the full arXiv repository.

## Environment

Python 3.10 or newer is required.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirement.txt
```

## Run

Create a UTF-8 text file with one assigned arXiv ID per line. Blank lines and comments beginning with `#` are ignored.

```powershell
python src/crawl_arxiv.py --ids assigned_ids.txt --output data/corpus
```

An optional Semantic Scholar API key can be passed with `--semantic-scholar-api-key` or provided in the `S2_API_KEY` environment variable. Keep the assigned ID file and generated data out of the public source repository.

## Output

Each paper has a folder containing per-version metadata, extracted source files, and a `references.json` file with all references returned by Semantic Scholar. Only `.tex` and `.bib` files are retained from each source archive; TeX figure commands remain unchanged. The temporary source archive is deleted after extraction.

The output also includes `papers.jsonl`, `references.jsonl`, and `metrics.json`. The references table contains only rows with an arXiv ID. Metrics include crawl duration, resolved-paper and version counts, archive and extracted-source sizes, reference coverage, output size, and sampled process memory. These JSON files are local working data and should not be committed.