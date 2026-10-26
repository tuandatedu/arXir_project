# Colab flow — Fast Crawl → Recovery → Export

This is a self-contained notebook flow for the **arXiv crawler** part of Milestone 1.
It is designed to run from a **GitHub feature branch** and save checkpoint archives to Google Drive.

## Files to copy to the branch

- `src/m1_crawling/run_arxiv_only.py` — updated recovery behavior: keep successful versions and retry only failed versions.
- `src/m1_crawling/export_reports.py` — report exporter.
- `src/m1_crawling/colab_shared_crawler.ipynb` — Colab notebook.
- `tests/test_arxiv_crawler.py` — offline regression tests (optional if teammate has other changes).

The existing crawler modules `arxiv_http.py`, `download.py`, `discover.py`, `assigned_ranges.py`, `src/common/config.py`, etc. are still required. **Do not upload only these four files into an empty repo.**

## Run in Colab

1. Push the files to your **feature branch**, not `main`.
2. Open `colab_shared_crawler.ipynb` from GitHub or upload to Colab.
3. Change `REPO_URL` and `BRANCH` in section 1.
4. Set CPU-only runtime, run clone/install/test, mount Google Drive.
5. Choose your assigned `RANGE_ID` (1–5) and `BATCH_SIZE` (50 recommended). **Keep the same batch size for the same backup folder.**
6. Run `fast_crawl(batches=1)` (no retries). Check archives with `show_checkpoints()`.
7. Run `recovery_crawl(batches=1, retries=0)` when appropriate. It copies original failed checkpoints to `_before_recovery/` once, then updates the original archive and marker.
8. Run `export_report()` to create reports. Run again after subsequent batches or recovery.

Recovery will skip `ok`, `no_tex`, and `not_found` papers and will **not redownload already successful versions** of an error paper. If a successful version's saved TeX/BibTeX file is missing, that version is downloaded again. If the source is still unavailable, it stays in the error list.

## Output

`DATA_DIR`:

```text
batch_00000.tar.gz       # paper metadata + extracted .tex/.bib + statuses
batch_00000.json         # completion manifest
_before_recovery/        # original snapshots of error batches
reports/
    papers.csv
    crawl_records.csv
    metrics.csv
    failed_versions.csv
    summary.json
```

`failed_versions.csv` has one row for each failed version, including ID, version, reason and batch. For an error in metadata discovery, it contains an empty version and the top-level error reason.

## Notes

- `--retries 0` skips retry **after a failed HTTP request**; it cannot avoid waiting for the configured network timeout on a broken download.
- Keep the crawler's request pacing and never run parallel sessions against arXiv. On HTTP 429, wait before trying again.
- The `metrics.json` stored inside an updated checkpoint reports the **latest run for that batch**, not the cumulative Fast + Recovery time. Keep a copy of the Fast report for comparisons.
- CSV arXiv IDs must be read as strings: `pd.read_csv('papers.csv', dtype={'arxiv_id': 'string'})`.
- Share `batch_*.tar.gz` archives with the Data Processing teammate; `papers.csv` contains only metadata.
- Offline tests: `python -m pytest -q tests/test_arxiv_crawler.py`.
