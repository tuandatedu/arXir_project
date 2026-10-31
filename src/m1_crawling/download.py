"""Bounded streaming source downloads + secure extraction of only .tex/.bib."""
from __future__ import annotations

import gzip
from http.client import IncompleteRead
import io
import logging
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time
from typing import Literal
import zipfile

import requests

from src.common.ids import versioned_id
from src.m1_crawling.arxiv_http import ArxivHTTP

LOG = logging.getLogger(__name__)

ArchiveKind = Literal["targz", "tar", "zip", "gz", "tex", "pdf", "unknown", "empty"]
SOURCE_MIRROR = "https://export.arxiv.org/src"
SUFFIXES = {".tex", ".bib"}
MAX_ARCHIVE_BYTES = 400 * 1024 * 1024  # protect Colab disk
MAX_FILE_BYTES = 32 * 1024 * 1024       # protect against decompression bombs
MAX_TOTAL_EXTRACTED = 120 * 1024 * 1024
MAX_FILES = 5000
STREAM_ATTEMPTS = 3  # re-download when the connection drops mid-stream
# Raised while reading the body, i.e. AFTER ArxivHTTP.get() returned, so its own retry never sees them.
STREAM_ERRORS = (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
                 requests.exceptions.ReadTimeout, IncompleteRead)


def source_url(arxiv_id: str, version: int) -> str:
    """Versioned /src/ URL; accepts new-style (2310.12345) and old-style IDs."""
    # versioned_id validates the version and strips any existing suffix first.
    return f"{SOURCE_MIRROR}/{versioned_id(arxiv_id, version)}"


def download_source_archive(arxiv_id: str, version: int, dest_path: Path,
                            http: ArxivHTTP | None = None,
                            max_bytes: int = MAX_ARCHIVE_BYTES,
                            attempts: int = STREAM_ATTEMPTS) -> Path:
    """Writes in 256KiB chunks, deletes partial files on every error.

    A connection that breaks mid-body (ChunkedEncodingError / IncompleteRead) is retried
    from the start up to ``attempts`` times with 5 s, 15 s ... waits; every attempt still
    goes through the shared 3 s request gate. HTTP status errors and size-limit errors are
    not retried here.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    own = http is None
    http = http or ArxivHTTP()
    partial = dest_path.with_name(dest_path.name + ".partial")
    try:
        for attempt in range(1, max(1, attempts) + 1):
            try:
                with http.get(source_url(arxiv_id, version), stream=True) as response:
                    count = 0
                    with partial.open("wb") as out:
                        for chunk in response.iter_content(chunk_size=256 * 1024):
                            if chunk:
                                count += len(chunk)
                                if count > max_bytes:
                                    raise ValueError(f"Archive exceeds {max_bytes} bytes")
                                out.write(chunk)
                partial.replace(dest_path)
                return dest_path
            except STREAM_ERRORS as exc:
                partial.unlink(missing_ok=True)
                if attempt >= attempts:
                    raise
                wait = 5 * 3 ** (attempt - 1)
                LOG.warning("%sv%s download broke (%s); attempt %d/%d, retry in %ds",
                            arxiv_id, version, type(exc).__name__, attempt, attempts, wait)
                time.sleep(wait)
        raise AssertionError("unreachable")
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        if own:
            http.close()


def detect_archive_kind(archive_path: Path) -> ArchiveKind:
    path = Path(archive_path)
    if not path.exists() or path.stat().st_size == 0:
        return "empty"
    with path.open("rb") as handle:
        prefix = handle.read(1024)
    if prefix.startswith(b"%PDF-"):
        return "pdf"
    if zipfile.is_zipfile(path):
        return "zip"
    if tarfile.is_tarfile(path):
        return "targz" if prefix[:2] == b"\x1f\x8b" else "tar"
    if prefix[:2] == b"\x1f\x8b":
        return "gz"  # single compressed TeX or other content
    if (b"\\documentclass" in prefix or b"\\begin{document}" in prefix
            or prefix.startswith((b"%", b"\\"))):
        return "tex"
    return "unknown"


def _safe_relative(name: str) -> Path | None:
    if "\\" in name or "\x00" in name:
        return None
    parts = PurePosixPath(name).parts
    if not parts or any(part in ("..", "") for part in parts):
        return None
    if PurePosixPath(name).is_absolute() or parts[0].endswith(":"):
        return None
    return Path(*parts)


def _copy_bounded(src: object, dest: Path, budget: list[int]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    copied = 0
    try:
        with tmp.open("wb") as target:
            while True:
                block = src.read(64 * 1024)
                if not block:
                    break
                copied += len(block)
                if copied > MAX_FILE_BYTES or budget[0] + copied > MAX_TOTAL_EXTRACTED:
                    raise ValueError("TeX/BibTeX expanded size limit exceeded")
                target.write(block)
        budget[0] += copied
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def extract_tex_and_bib(archive_path: Path, out_dir: Path) -> list[Path]:
    """No image binaries, no symlinks, no path traversal, preserve .tex bytes."""
    archive_path, out_dir = Path(archive_path), Path(out_dir)
    kind = detect_archive_kind(archive_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    budget = [0]
    if kind in ("pdf", "empty"):
        return extracted
    if kind in ("targz", "tar"):
        with tarfile.open(archive_path, "r:*") as archive:
            for i, member in enumerate(archive):
                if i >= MAX_FILES:
                    raise ValueError("Archive contains too many members")
                relative = _safe_relative(member.name)
                if (not member.isfile() or relative is None
                        or relative.suffix.lower() not in SUFFIXES):
                    continue
                if member.size > MAX_FILE_BYTES:
                    raise ValueError(f"TeX/BibTeX file too large: {member.name}")
                opened = archive.extractfile(member)
                if opened is not None:
                    with opened:
                        dest = out_dir / relative
                        _copy_bounded(opened, dest, budget)
                        extracted.append(dest)
    elif kind == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            for i, item in enumerate(archive.infolist()):
                if i >= MAX_FILES:
                    raise ValueError("ZIP contains too many members")
                relative = _safe_relative(item.filename)
                if (item.is_dir() or relative is None or
                        relative.suffix.lower() not in SUFFIXES):
                    continue
                # Unix symlink in ZIP.
                if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                    continue
                if item.file_size > MAX_FILE_BYTES:
                    raise ValueError(f"TeX/BibTeX file too large: {item.filename}")
                with archive.open(item) as opened:
                    dest = out_dir / relative
                    _copy_bounded(opened, dest, budget)
                    extracted.append(dest)
    elif kind in ("gz", "tex"):
        dest = out_dir / "main.tex"
        if kind == "gz":
            with gzip.open(archive_path, "rb") as opened:
                # Single gzip can be a binary document; don't save as fake .tex.
                head = opened.read(512)
                if head.startswith(b"%PDF-") or b"\x00" in head or not (b"\\" in head or b"%" in head):
                    return []
            with gzip.open(archive_path, "rb") as opened:
                _copy_bounded(opened, dest, budget)
        else:
            with archive_path.open("rb") as opened:
                _copy_bounded(opened, dest, budget)
        extracted.append(dest)
    else:
        raise ValueError("Unrecognized source archive, not safe to label PDF-only")
    return extracted


def cleanup_temp_archive(archive_path: Path) -> None:
    Path(archive_path).unlink(missing_ok=True)