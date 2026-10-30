"""End-to-end orchestration for one publication or an assigned ID file."""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from src.common.config import TABLES_DIR, WORKING_DIR
from src.common.io import load_assigned_ids, read_json
from src.common.metrics import track_run, directory_size_bytes
from src.common.schemas import PaperRow, ReferenceRow
from src.common.ids import normalize_arxiv_id
from .analyze import corpus_stats, write_metrics
from .arxiv_http import ArxivHTTP
from .corpus import (iter_publications, publication_dir, version_source_dir,
                     save_paper_meta, save_references, save_version_sources)
from .discover import PaperMeta, fetch_papers_by_ids, list_versions
from .download import cleanup_temp_archive, detect_archive_kind, download_source_archive, extract_tex_and_bib
from .semantic_scholar import fetch_s2_references, s2_ref_to_local_record
from .tables import paper_meta_to_row, s2_records_to_reference_rows, write_m1_tables

LOG = logging.getLogger(__name__)


def crawl_one_publication(arxiv_id: str, *, s2_api_key: Optional[str] = None,
                          http: ArxivHTTP | None = None,
                          working_dir: Path | None = None) -> dict:
    """Resolve a paper, process every version, then fetch its S2 references once."""
    # Normalize once so every local folder and API call uses the same base ID.
    arxiv_id = normalize_arxiv_id(arxiv_id)
    # Reuse the caller's paced client, or create/close one for a standalone call.
    own_http = http is None
    http = http or ArxivHTTP()
    started = time.perf_counter()
    # Accumulate simple values that are safe to write into the JSON metrics file.
    result = {"arxiv_id": arxiv_id, "status": "failed", "n_versions": 0,
              "n_empty_versions": 0, "n_tex_bib_files": 0,
              "archive_bytes": 0, "extracted_bytes": 0,
              "semantic_scholar_reference_count": 0,
              "semantic_scholar_status": "not_attempted", "errors": []}
    try:
        # Use one shared HTTP client so every arXiv request obeys one 3-second gate.
        # Resolve the latest Atom entry; its version number determines the full list.
        discovery_started = time.perf_counter()
        try:
            meta = fetch_papers_by_ids([arxiv_id], http=http).get(arxiv_id)
        except Exception as exc:
            result["discovery_seconds"] = round(time.perf_counter() - discovery_started, 6)
            result["errors"].append({"stage": "discovery", "error": str(exc)})
            return result
        result["discovery_seconds"] = round(time.perf_counter() - discovery_started, 6)
        if meta is None:
            result["errors"].append({"stage": "discovery", "error": "paper_not_found"})
            return result
        # Save metadata before downloads so a later failure does not lose the paper record.
        save_paper_meta(arxiv_id, meta, working_dir)
        versions = list_versions(meta)
        result["n_versions"] = len(versions)

        # Download and process every version independently, so one failure does not stop others.
        for version in versions:
            destination = version_source_dir(arxiv_id, version, working_dir)
            # Keep the original archive temporary; only selected text files enter the corpus.
            # Keep temporary archives under the corpus root so disk sampling includes them.
            with tempfile.TemporaryDirectory(
                prefix=f".tmp-arxiv-{arxiv_id}-v{version}-",
                dir=publication_dir(arxiv_id, working_dir),
            ) as temp:
                archive = Path(temp) / "source.archive"
                try:
                    download_source_archive(arxiv_id, version, archive, http=http)
                    result["archive_bytes"] += archive.stat().st_size
                    # Detect PDF/source formats before extracting the allowed file types.
                    kind = detect_archive_kind(archive)
                    files = extract_tex_and_bib(archive, destination)
                    # A version with no TeX/Bib files still receives an empty marker.
                    if not files:
                        result["n_empty_versions"] += 1
                        reason = "pdf_only" if kind == "pdf" else "no_tex_or_bib"
                        save_version_sources(arxiv_id, version, [], empty=True, reason=reason,
                                             working_dir=working_dir)
                    else:
                        result["n_tex_bib_files"] += len(files)
                        result["extracted_bytes"] += sum(p.stat().st_size for p in files)
                        # The extractor already wrote into the final folder.
                        save_version_sources(arxiv_id, version, files, empty=False,
                                             working_dir=working_dir)
                except Exception as exc:
                    # Record the failure and continue with the next version.
                    result["errors"].append({"version": version, "error": str(exc)})
                    result["n_empty_versions"] += 1
                    save_version_sources(arxiv_id, version, [], empty=True,
                                         reason=f"download_or_extract_error: {exc}",
                                         working_dir=working_dir)
                    LOG.exception("Failed to process %s v%s", arxiv_id, version)
                finally:
                    cleanup_temp_archive(archive)

        # S2 has no version-specific reference list, so one request covers the paper.
        # Semantic Scholar indexes references per publication, not per arXiv version.
        try:
            raw_refs = fetch_s2_references(arxiv_id, api_key=s2_api_key)
            local_refs = [s2_ref_to_local_record(arxiv_id, ref) for ref in raw_refs]
            result["semantic_scholar_status"] = "success"
        except Exception as exc:
            LOG.exception("Semantic Scholar lookup failed for %s", arxiv_id)
            result["errors"].append({"stage": "semantic_scholar", "error": str(exc)})
            result["semantic_scholar_status"] = "failed"
            local_refs = []
        # Preserve all references locally; the references table filters by arXiv ID later.
        save_references(arxiv_id, local_refs, working_dir)
        result["semantic_scholar_reference_count"] = len(local_refs)
        result["status"] = "success" if not result["errors"] else "partial"
        return result
    finally:
        # Include elapsed time even if discovery or processing raises an exception.
        result["duration_sec"] = round(time.perf_counter() - started, 6)
        if own_http:
            http.close()


def run_milestone1(ids_file: Path, *, s2_api_key: Optional[str] = None,
                   output_dir: Path | None = None,
                   tables_dir: Path | None = None,
                   metrics_path: Path | None = None) -> tuple[list[PaperRow], list[ReferenceRow]]:
    """Crawl each assigned ID, keep going after individual failures, and export tables."""
    # Load and de-duplicate the assigned IDs before contacting either API.
    ids = load_assigned_ids(ids_file)
    # Let the user redirect corpus files without changing the project defaults.
    working_dir = Path(output_dir) if output_dir is not None else WORKING_DIR
    output_tables = Path(tables_dir) if tables_dir is not None else TABLES_DIR
    working_dir.mkdir(parents=True, exist_ok=True)
    papers: list[PaperRow] = []
    references: list[ReferenceRow] = []
    crawl_results: list[dict] = []
    # Sample folder size during the crawl to estimate peak on-disk usage.
    disk_stop = threading.Event()
    def retained_output_bytes() -> int:
        """Measure the corpus plus table output folders being produced by this run."""
        paths = dict.fromkeys((working_dir, output_tables))
        return sum(directory_size_bytes(path) for path in paths)

    disk_samples = [retained_output_bytes()]

    def sample_disk() -> None:
        """Periodically sample corpus size while crawling to estimate the peak."""
        while not disk_stop.wait(0.5):
            disk_samples.append(retained_output_bytes())

    disk_sampler = threading.Thread(target=sample_disk, name="disk-usage-sampler", daemon=True)
    disk_sampler.start()
    # Share one arXiv rate gate across every paper and measure the full pipeline.
    with ArxivHTTP() as http, track_run("m1") as runtime:
        for arxiv_id in ids:
            paper_started = time.perf_counter()
            # Isolate each paper so one bad ID does not discard the rest of the assignment.
            try:
                item = crawl_one_publication(arxiv_id, s2_api_key=s2_api_key,
                                             http=http, working_dir=working_dir)
                crawl_results.append(item)
            except Exception as exc:
                LOG.exception("Could not crawl assigned paper %s", arxiv_id)
                crawl_results.append({
                    "arxiv_id": arxiv_id,
                    "status": "failed",
                    "duration_sec": round(time.perf_counter() - paper_started, 6),
                    "error": str(exc),
                })

        # Rebuild tables from the whole corpus so each batch keeps prior rows.
        for corpus_id in iter_publications(working_dir):
            paper_data = read_json(publication_dir(corpus_id, working_dir) / "paper.json")
            meta = PaperMeta(**{key: paper_data[key] for key in (
                "arxiv_id", "title", "authors", "abstract", "latest_version",
                "submission_date", "revised_dates", "venue", "categories", "raw")})
            papers.append(paper_meta_to_row(meta))
            refs_path = publication_dir(corpus_id, working_dir) / "references.json"
            if refs_path.exists():
                references.extend(s2_records_to_reference_rows(corpus_id, read_json(refs_path)))

        # Write tables after every call, including rows from earlier batches.
        # Tables and metrics can be redirected to Drive for persistent Colab output.
        write_m1_tables(papers, references, tables_dir=tables_dir)
        disk_samples.append(retained_output_bytes())
    # Stop the background disk sampler before saving its final peak measurement.
    disk_stop.set()
    disk_sampler.join()
    # track_run populates duration/RAM after leaving the context.
    # track_run fills duration and RAM fields when its context exits.
    stats = corpus_stats(
        working_dir,
        assigned_ids=ids,
        crawl_results=crawl_results,
        runtime_metrics=runtime,
        max_disk_usage_bytes=max(disk_samples),
        additional_output_dirs=[output_tables],
    )
    write_metrics(stats, path=metrics_path)
    return papers, references
