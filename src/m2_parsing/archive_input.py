"""Restore M1 batch checkpoints as the working corpus expected by M2."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath


def restore_batch(archive: Path, working_dir: Path) -> int:
    """Verify one M1 checkpoint, then safely restore only its ``working/`` files."""
    archive, working_dir = Path(archive), Path(working_dir)
    manifest = archive.with_name(archive.name.removesuffix(".tar.gz") + ".json")
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if archive.stat().st_size != expected.get("archive_bytes") or digest.hexdigest() != expected.get("archive_sha256"):
        raise ValueError(f"Checkpoint checksum mismatch: {archive}")
    written = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] != "working" or len(parts) < 2:
                continue
            if any(part in (".", "..") for part in parts) or not member.isfile():
                continue
            target = working_dir.joinpath(*parts[1:])
            if not target.resolve().is_relative_to(working_dir.resolve()):
                raise ValueError(f"Unsafe archive path: {member.name}")
            source = bundle.extractfile(member)
            if source is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    output.write(block)
            written += 1
    return written


def restore_batches(batch_dir: Path, working_dir: Path) -> int:
    archives = sorted(Path(batch_dir).glob("batch_*.tar.gz"))
    if not archives:
        raise FileNotFoundError(f"No batch archives in {batch_dir}")
    return sum(restore_batch(archive, working_dir) for archive in archives)
