# Colab flow — Fast Crawl → Recovery → Export

This is a self-contained notebook flow for the **arXiv crawler** part of Milestone 1.
It is designed to run from a **GitHub feature branch** and save checkpoint archives to Google Drive.

## Files to copy to the branch

- `src/m1_crawling/run_arxiv_only.py` — concurrent paper workers + updated recovery behavior: keep successful versions and retry only failed versions.
- `src/m1_crawling/arxiv_http.py` — shared one-connection HTTP gate and global request pacing.
- `src/m1_crawling/export_reports.py` — report exporter.
- `src/m1_crawling/colab_shared_crawler.ipynb` — Colab notebook.
- `tests/test_concurrent_crawler.py` — offline concurrency/rate-limit/recovery regression tests.

The existing crawler modules `arxiv_http.py`, `download.py`, `discover.py`, `assigned_ranges.py`, `src/common/config.py`, etc. are still required. **Do not upload only these four files into an empty repo.**

## Run in Colab

1. Push the files to your **feature branch**, not `main`.
2. Open `colab_shared_crawler.ipynb` from GitHub or upload to Colab.
3. Change `REPO_URL` and `BRANCH` in section 1.
4. Set CPU-only runtime, run clone/install/test, mount Google Drive.
5. Choose your assigned `RANGE_ID` (1–5) and `BATCH_SIZE` (50 recommended). **Keep the same batch size for the same backup folder.**
6. Set `MAX_WORKERS = 3` (or 1 to revert to sequential), then run `fast_crawl(batches=1)` (no retries). Check archives with `show_checkpoints()`.
7. Run `recovery_crawl(batches=100, retries=1)` when appropriate. Recovery **only** processes already existing failed checkpoints, and **does not** create new batches. `backup_before=False` avoids duplicate archives; set True only when a snapshot is needed.
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
- The worker pool is for **paper processing** (downloads/extraction); the HTTP client enforces **global** pacing (at least 3.1 seconds between request starts), while allowing workers to wait for responses and stream downloads concurrently. This is not a way to multiply arXiv request rate.
- On HTTP 429, the shared cooldown respects `Retry-After`. Never run two Colab notebooks simultaneously against the same Drive checkpoint directory.
- Keep `BATCH_SIZE` unchanged when resuming. `MAX_WORKERS` may be changed freely (1..4).
- `metrics.csv` has optional `workers_this_run` for newly generated checkpoints. Existing checkpoint/report formats remain readable.
- The `metrics.json` stored inside an updated checkpoint reports the **latest run for that batch**, not the cumulative Fast + Recovery time. Keep a copy of the Fast report for comparisons.
- CSV arXiv IDs must be read as strings: `pd.read_csv('papers.csv', dtype={'arxiv_id': 'string'})`.
- Share `batch_*.tar.gz` archives with the Data Processing teammate; `papers.csv` contains only metadata.
- Offline tests: `python -m pytest -q tests/test_arxiv_crawler.py tests/test_runtime_tracking.py tests/test_concurrent_crawler.py`.
