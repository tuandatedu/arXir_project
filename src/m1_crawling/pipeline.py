"""
Orchestrator M1: assigned IDs → working corpus + bảng papers/references + metrics.

Chạy end-to-end (wall-clock = runtime hệ thống) trên Colab CPU-only khi benchmark.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.common.ids import normalize_arxiv_id
from src.common.io import load_assigned_ids
from src.common.metrics import track_run
from src.common.schemas import PaperRow, ReferenceRow

from .analyze import corpus_stats, write_metrics
from .corpus import (
    publication_dir,
    save_paper_meta,
    save_s2_references,
    save_version_sources,
    version_source_dir,
)
from .discover import fetch_paper_by_id, list_versions
from .download import (
    cleanup_temp_archive,
    detect_archive_kind,
    download_source_archive,
    extract_tex_and_bib,
)
from .arxiv_http import ArxivHTTP, ArxivHTTPError
from .semantic_scholar import fetch_s2_references, s2_ref_to_local_record
from .tables import (
    paper_meta_to_row,
    s2_records_to_reference_rows,
    validate_m1_tables,
    write_m1_tables,
)

LOG = logging.getLogger(__name__)


def crawl_one_publication(arxiv_id: str, *, s2_api_key: Optional[str] = None) -> dict:
    """
    Crawl 1 paper: discover → mọi version /src/ → extract tex/bib → S2 refs.

    1. fetch_paper_by_id + list_versions
    2. save_paper_meta
    3. với mỗi version: download_source_archive, detect_archive_kind,
       extract_tex_and_bib hoặc empty record, cleanup_temp_archive
    4. fetch_s2_references (1 lần / publication, không / version — S2 không phân version)
    5. return dict tóm tắt (meta, n_versions, n_tex, n_refs, errors)

    Tôn trọng ARXIV_MIN_DELAY_SEC và S2_MIN_DELAY_SEC. Một connection tại một thời điểm.
    """
    base = normalize_arxiv_id(arxiv_id)
    meta = fetch_paper_by_id(base)
    versions = list_versions(meta)
    save_paper_meta(base, meta)

    summary: dict = {
        "arxiv_id": base,
        "status": "ok",
        "meta": meta,
        "n_versions": len(versions),
        "n_tex": 0,
        "n_refs": 0,
        "n_refs_with_arxiv": 0,
        "bytes_archive": 0,
        "bytes_extracted": 0,
        "errors": [],
    }

    with ArxivHTTP() as http:
        for version in versions:
            archive_path = publication_dir(base) / f"_archive_v{version}.tar.gz"
            reason = ""
            extracted: list[Path] = []
            archive_bytes = 0
            try:
                download_source_archive(base, version, archive_path, http=http)
                archive_bytes = archive_path.stat().st_size
                kind = detect_archive_kind(archive_path)
                if kind in ("pdf", "empty"):
                    reason = "pdf-only" if kind == "pdf" else "empty archive"
                else:
                    out_dir = version_source_dir(base, version)
                    try:
                        extracted = extract_tex_and_bib(archive_path, out_dir)
                    except ValueError as exc:
                        reason = f"unsafe archive: {exc}"
                        extracted = []
                    if not extracted and not reason:
                        reason = "no tex/bib in archive"
            except (ArxivHTTPError, ValueError) as exc:
                reason = str(exc)
                summary["errors"].append(f"v{version}: {exc}")
                LOG.warning("Source download/extract failed for %sv%s: %s",
                            base, version, exc)
            finally:
                cleanup_temp_archive(archive_path)

            save_version_sources(base, version, extracted,
                                 empty=not extracted, reason=reason)
            if extracted:
                summary["n_tex"] += len(extracted)
                summary["bytes_extracted"] += sum(
                    path.stat().st_size for path in extracted
                    if path.exists())
            summary["bytes_archive"] += archive_bytes
            # Version-level bookkeeping (dùng bởi analyze.corpus_stats).
            from src.common.io import write_json
            write_json(publication_dir(base) / f"v{version}" / "metadata.json", {
                "version": version,
                "status": "ok" if extracted else "no_tex",
                "reason": reason,
                "archive_bytes": archive_bytes,
                "n_files": len(extracted),
                "extracted_bytes": sum(path.stat().st_size for path in extracted
                                       if path.exists()),
            })

    # S2 không phân version — gọi đúng một lần cho publication.
    raw_records = fetch_s2_references(base, api_key=s2_api_key)
    records = [s2_ref_to_local_record(base, raw) for raw in raw_records]
    save_s2_references(base, records)
    summary["n_refs"] = len(records)
    summary["n_refs_with_arxiv"] = sum(1 for r in records if r.get("ref_arxiv_id"))
    return summary


def _dedupe_papers(rows: list[PaperRow]) -> list[PaperRow]:
    seen: set[str] = set()
    out: list[PaperRow] = []
    for row in rows:
        if row.arxiv_id in seen:
            continue
        seen.add(row.arxiv_id)
        out.append(row)
    return out


def _dedupe_references(rows: list[ReferenceRow]) -> list[ReferenceRow]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ReferenceRow] = []
    for row in rows:
        key = (row.arxiv_id, row.ref_arxiv_id, row.ref_s2_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def run_milestone1(
    ids_file: Path,
    *,
    s2_api_key: Optional[str] = None,
) -> tuple[list[PaperRow], list[ReferenceRow]]:
    """
    Entry chính M1.

    - load_assigned_ids
    - track_run('m1') bọc vòng lặp crawl_one_publication
    - ghi tables + metrics
    - lỗi 1 paper: log + tiếp tục (không abort cả range)
    """
    arxiv_ids = load_assigned_ids(Path(ids_file))
    LOG.info("M1: %d assigned IDs from %s", len(arxiv_ids), ids_file)

    papers: list[PaperRow] = []
    references: list[ReferenceRow] = []
    failures: list[dict] = []
    per_paper: list[dict] = []

    with track_run("m1") as metrics:
        metrics["n_assigned"] = len(arxiv_ids)
        for arxiv_id in arxiv_ids:
            try:
                result = crawl_one_publication(arxiv_id, s2_api_key=s2_api_key)
            except Exception as exc:  # một paper lỗi không được abort cả range
                LOG.error("Failed to crawl %s: %s", arxiv_id, exc)
                failures.append({"arxiv_id": arxiv_id, "error": str(exc)})
                continue
            papers.append(paper_meta_to_row(result["meta"]))
            references.extend(
                s2_records_to_reference_rows(result["arxiv_id"],
                                             _load_local_refs(result["arxiv_id"])))
            per_paper.append({key: value for key, value in result.items()
                              if key != "meta"})

        papers = _dedupe_papers(papers)
        references = _dedupe_references(references)

        validation = validate_m1_tables(papers, references)
        write_m1_tables(papers, references)

        stats = corpus_stats()
        metrics.update({
            "n_ok": len(papers),
            "n_failed": len(failures),
            "failures": failures,
            "n_papers": len(papers),
            "n_references": len(references),
            "n_s2_refs_total": sum(p.get("n_refs", 0) for p in per_paper),
            "n_s2_refs_with_arxiv": sum(p.get("n_refs_with_arxiv", 0)
                                        for p in per_paper),
            "bytes_archive": sum(p.get("bytes_archive", 0) for p in per_paper),
            "bytes_extracted": sum(p.get("bytes_extracted", 0) for p in per_paper),
            "validation_ok": validation["ok"],
            "validation_n_issues": validation["n_issues"],
            "validation_issues": validation["issues"][:200],
        })
        metrics.update({f"corpus_{key}": value for key, value in stats.items()
                        if key not in metrics})
        write_metrics(metrics)

    if not validation["ok"]:
        LOG.warning("M1 tables have %d validation issues (see metrics_m1.json)",
                    validation["n_issues"])
    LOG.info("M1 finished: %d papers, %d references, %d failures",
             len(papers), len(references), len(failures))
    return papers, references


def _load_local_refs(arxiv_id: str) -> list[dict]:
    from src.common.io import read_jsonl
    path = publication_dir(arxiv_id) / "references_s2.json"
    return read_jsonl(path) if path.exists() else []
