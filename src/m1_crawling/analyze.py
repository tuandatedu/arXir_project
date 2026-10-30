"""Build auditable M1 corpus and runtime metrics for the project report."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from src.common.config import TABLES_DIR
from src.common.io import read_json, write_json
from src.common.metrics import directory_size_bytes


def corpus_stats(
    working_dir: Path,
    *,
    assigned_ids: Iterable[str] | None = None,
    crawl_results: list[dict[str, Any]] | None = None,
    runtime_metrics: dict[str, Any] | None = None,
    max_disk_usage_bytes: int | None = None,
    additional_output_dirs: Iterable[Path] = (),
) -> dict[str, Any]:
    """Summarize corpus coverage, source/reference sizes, run time, RAM, and disk.

    Archive sizes and per-paper timings cannot be reconstructed from extracted files
    after temporary archives have been deleted, so pass ``crawl_results`` from the run.
    """
    root = Path(working_dir)
    paper_files = sorted(root.glob("*/paper.json")) if root.exists() else []
    run_rows = crawl_results or []
    runtime = runtime_metrics or {}

    # Counts and byte totals that can be measured directly from the saved corpus.
    n_versions = 0
    n_empty_versions = 0
    extracted_bytes = 0
    total_refs = 0
    refs_with_arxiv = 0
    refs_with_metadata = 0
    papers_with_semantic_scholar_data = 0

    for paper_file in paper_files:
        publication = paper_file.parent
        metadata = read_json(paper_file)
        versions = metadata.get("versions") or list(
            range(1, int(metadata.get("latest_version", 1)) + 1)
        )
        n_versions += len(versions)

        # Empty markers include PDF-only versions and versions that failed to download.
        for version in versions:
            if (publication / f"v{version}" / "empty.json").is_file():
                n_empty_versions += 1

        # Count only extracted LaTeX and BibTeX files, never figures or archives.
        for source in publication.glob("v*/sources/**/*"):
            if source.is_file() and source.suffix.lower() in {".tex", ".bib"}:
                extracted_bytes += source.stat().st_size

        # The local references file retains records even when they have no arXiv ID.
        refs_path = publication / "references.json"
        if refs_path.is_file():
            papers_with_semantic_scholar_data += 1
            refs = read_json(refs_path)
            if isinstance(refs, list):
                for ref in refs:
                    if not isinstance(ref, dict):
                        continue
                    total_refs += 1
                    refs_with_arxiv += bool(ref.get("ref_arxiv_id"))
                    # A reference is considered populated if S2 returned any useful fields.
                    has_metadata = any((
                        ref.get("ref_title"), ref.get("ref_authors"),
                        ref.get("ref_submission_date"), ref.get("ref_s2_id"),
                    ))
                    refs_with_metadata += bool(has_metadata)

    n_resolved = len(paper_files)
    ids = list(assigned_ids) if assigned_ids is not None else None
    n_assigned = len(ids) if ids is not None else None

    # Use per-run records for measurements that disappear with the temporary archives.
    archive_bytes = sum(int(row.get("archive_bytes", 0) or 0) for row in run_rows)
    archive_papers = sum(int(row.get("archive_bytes", 0) or 0) > 0 for row in run_rows)
    successful = sum(row.get("status") == "success" for row in run_rows)
    partial = sum(row.get("status") == "partial" for row in run_rows)
    failed = sum(row.get("status") == "failed" for row in run_rows)
    durations = [float(row["duration_sec"]) for row in run_rows
                 if row.get("duration_sec") is not None]
    discovery_durations = [float(row["discovery_seconds"]) for row in run_rows
                           if row.get("discovery_seconds") is not None]

    # S2 request success is counted separately from how many references have arXiv IDs.
    semantic_scholar_attempted = sum(
        row.get("semantic_scholar_status") in {"success", "failed"} for row in run_rows
    )
    semantic_scholar_succeeded = sum(
        row.get("semantic_scholar_status") == "success" for row in run_rows
    )
    semantic_scholar_failed = sum(
        row.get("semantic_scholar_status") == "failed" for row in run_rows
    )

    # Calculate final retained size across corpus and requested table output folders.
    output_dirs = [root, *(Path(p) for p in additional_output_dirs)]
    final_output_bytes = sum(directory_size_bytes(path) for path in dict.fromkeys(output_dirs))

    return {
        # Discovery and crawl coverage.
        "n_assigned": n_assigned,
        "n_resolved": n_resolved,
        "n_successful": successful,
        "n_partial": partial,
        "n_failed": failed,
        "overall_success_rate": successful / n_assigned if n_assigned else None,
        "n_versions": n_versions,
        "n_empty_versions": n_empty_versions,
        # Source size before/after extraction (the archive is measured during the run).
        "archive_bytes": archive_bytes if run_rows else None,
        "archive_papers_measured": archive_papers,
        "avg_archive_bytes_per_paper": archive_bytes / archive_papers if archive_papers else None,
        "extracted_bytes": extracted_bytes,
        "avg_extracted_bytes_per_paper": extracted_bytes / n_resolved if n_resolved else 0,
        # Reference counts and two distinct coverage measures.
        "n_semantic_scholar_references": total_refs,
        "references_with_arxiv_id": refs_with_arxiv,
        "avg_refs_per_paper": total_refs / n_resolved if n_resolved else 0,
        "reference_arxiv_id_coverage": refs_with_arxiv / total_refs if total_refs else None,
        "reference_metadata_completeness": refs_with_metadata / total_refs if total_refs else None,
        "papers_with_semantic_scholar_data": papers_with_semantic_scholar_data,
        "semantic_scholar_requests_attempted": semantic_scholar_attempted,
        "semantic_scholar_requests_succeeded": semantic_scholar_succeeded,
        "semantic_scholar_requests_failed": semantic_scholar_failed,
        "semantic_scholar_request_success_rate": (
            semantic_scholar_succeeded / semantic_scholar_attempted
            if semantic_scholar_attempted else None
        ),
        # Wall-clock measurements from the crawl and discovery steps.
        "total_runtime_seconds": runtime.get("duration_sec"),
        "average_seconds_per_paper": sum(durations) / len(durations) if durations else None,
        "discovery_total_seconds": sum(discovery_durations) if discovery_durations else None,
        "discovery_average_seconds_per_paper": (
            sum(discovery_durations) / len(discovery_durations) if discovery_durations else None
        ),
        # RSS is sampled by track_run; disk peak is sampled by the pipeline.
        "peak_rss_bytes": runtime.get("peak_rss_bytes"),
        "average_rss_bytes": runtime.get("avg_rss_bytes"),
        "rss_sample_count": runtime.get("rss_sample_count"),
        "max_disk_usage_bytes": max_disk_usage_bytes,
        "final_output_bytes": final_output_bytes,
        "disk_measurement_scope": "corpus and additional output directories; excludes Colab runtime files",
        # Include per-paper details so report authors can audit and plot individual outcomes.
        "paper_runtime_seconds": durations,
        "crawl_results": run_rows,
    }


def write_metrics(payload: dict[str, Any], path: Path | None = None) -> Path:
    """Write UTF-8 JSON metrics for the report; create its parent directory as needed."""
    destination = Path(path) if path is not None else TABLES_DIR / "metrics_m1.json"
    write_json(destination, payload)
    return destination
