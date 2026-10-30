"""Filesystem layout and persistence helpers for the raw M1 corpus."""
from __future__ import annotations

import shutil
import os
from pathlib import Path
from typing import Any

from src.common.config import WORKING_DIR
from src.common.ids import folder_name_for_arxiv_id, normalize_arxiv_id
from src.common.io import read_json, write_json
from .discover import PaperMeta


def publication_dir(arxiv_id: str, working_dir: Path | None = None) -> Path:
    """Return the local folder for a publication (without creating it)."""
    # Allow callers to choose a custom corpus root; otherwise use the project default.
    root = Path(working_dir) if working_dir is not None else WORKING_DIR
    # Convert dots/slashes in an arXiv ID to characters safe for folder names.
    return root / folder_name_for_arxiv_id(arxiv_id)


def version_source_dir(arxiv_id: str, version: int, working_dir: Path | None = None) -> Path:
    """Return and create the .tex/.bib destination for one paper version."""
    # Version numbers start at one; reject accidental paths such as v0 or v-1.
    if version < 1:
        raise ValueError("version must be positive")
    # Keep each version's source files separate from metadata and other versions.
    path = publication_dir(arxiv_id, working_dir) / f"v{version}" / "sources"
    # Create the full directory tree; existing folders are fine for resumable runs.
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_paper_meta(arxiv_id: str, meta: PaperMeta, working_dir: Path | None = None) -> Path:
    """Store publication metadata once, with a stable base ID and version list."""
    # Make sure metadata returned by discovery belongs to the ID being saved.
    if normalize_arxiv_id(meta.arxiv_id) != normalize_arxiv_id(arxiv_id):
        raise ValueError("metadata ID does not match requested arXiv ID")
    # Store only the base ID in the publication record, not a version suffix.
    payload = {
        "arxiv_id": normalize_arxiv_id(arxiv_id), "title": meta.title,
        "authors": list(meta.authors), "abstract": meta.abstract,
        "submission_date": meta.submission_date,
        "revised_dates": list(meta.revised_dates), "venue": meta.venue,
        "categories": list(meta.categories),
        "latest_version": meta.latest_version,
        # This explicit list tells later steps exactly which source versions to fetch.
        "versions": list(range(1, meta.latest_version + 1)),
        # Keep the raw API fields too, so useful metadata is not lost during mapping.
        "raw": meta.raw,
    }
    # Put paper metadata beside its version folders, then return its location.
    path = publication_dir(arxiv_id, working_dir) / "paper.json"
    write_json(path, payload)
    return path


def save_version_sources(arxiv_id: str, version: int, extracted_files: list[Path],
                         *, empty: bool, reason: str = "",
                         working_dir: Path | None = None) -> None:
    """Copy extracted source files into the version folder or write an empty marker."""
    # Work out the version folder and the source-only subfolder.
    version_dir = publication_dir(arxiv_id, working_dir) / f"v{version}"
    target = version_source_dir(arxiv_id, version, working_dir)
    marker = version_dir / "empty.json"
    if empty or not extracted_files:
        # Keep the version visible even when it is PDF-only or has no source files.
        write_json(marker, {"empty": True, "reason": reason or "no_tex_or_bib"})
        return
    # A successful extraction supersedes a previous empty marker from a retry.
    marker.unlink(missing_ok=True)
    # Convert path-like inputs to Path objects so path operations work consistently.
    paths = [Path(p) for p in extracted_files]
    # The extractor writes beneath one temporary root; preserve subfolders when possible.
    try:
        common_root = Path(os.path.commonpath([str(p.parent) for p in paths]))
    except ValueError:
        # Different drives cannot have a common path on Windows; use the first parent.
        common_root = paths[0].parent
    for source in paths:
        # The corpus must contain source text and BibTeX, not figure binaries or PDFs.
        if source.suffix.lower() not in (".tex", ".bib"):
            continue
        # Avoid copying a file onto itself when extraction already used the final folder.
        if source.resolve().is_relative_to(target.resolve()):
            continue  # extraction already wrote to the final destination
        # Recreate any nested source subfolders under the final version directory.
        relative = source.relative_to(common_root)
        destination = target / relative
        # Ensure the destination's parent exists before copying the source file.
        destination.parent.mkdir(parents=True, exist_ok=True)
        # copy2 preserves file timestamps and metadata while leaving TeX contents unchanged.
        shutil.copy2(source, destination)


def save_references(arxiv_id: str, records: list[dict[str, Any]],
                    working_dir: Path | None = None) -> Path:
    """Keep every reference locally, including records without an arXiv ID."""
    # Save by data type; the JSON filename does not depend on which API supplied it.
    path = publication_dir(arxiv_id, working_dir) / "references.json"
    write_json(path, records)
    return path


def iter_publications(working_dir: Path | None = None) -> list[str]:
    """List base IDs with paper metadata, in deterministic order."""
    # Use the configured corpus root unless a caller supplies another one.
    root = Path(working_dir) if working_dir is not None else WORKING_DIR
    ids = []
    # Sorting makes repeated runs and generated reports deterministic.
    for path in sorted(root.glob("*/paper.json")):
        # Read the saved record instead of trying to reconstruct IDs from folder names.
        record = read_json(path)
        if record.get("arxiv_id"):
            # Normalize IDs so version suffixes never leak into publication keys.
            ids.append(normalize_arxiv_id(record["arxiv_id"]))
    return ids
