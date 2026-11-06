"""Build a separate M1 checkpoint set with recovered v1 sources included."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

from src.common.ids import folder_name_for_arxiv_id, normalize_arxiv_id
from src.common.io import write_json


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def build_repaired_checkpoints(batch_dir: Path, repairs_dir: Path, output_dir: Path) -> dict:
    """Copy checkpoints and replace only failed v1 records with recovered sources.

    ``repairs_dir/<folder>/sources`` contains the extracted files and the sibling
    ``source.tar.gz`` is the downloaded arXiv archive. Original checkpoints are
    never modified. Output must be a new, empty directory.
    """
    batch_dir, repairs_dir, output_dir = map(Path, (batch_dir, repairs_dir, output_dir))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    if output_dir.resolve() == batch_dir.resolve():
        raise ValueError("Output must differ from input")
    archives = sorted(batch_dir.glob('batch_*.tar.gz'))
    if not archives:
        raise FileNotFoundError(f'No batches in {batch_dir}')
    repairs = {}
    for folder in repairs_dir.iterdir():
        if not folder.is_dir() or not (folder / 'sources').is_dir():
            continue
        arxiv_id = normalize_arxiv_id(folder.name.replace('-', '.', 1))
        sources = sorted(p for p in (folder / 'sources').rglob('*')
                         if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.tex', '.bib'))
        if not sources or not any(p.suffix.lower() == '.tex' for p in sources):
            raise ValueError(f'No recovered TeX sources for {arxiv_id}')
        if not (folder / 'source.tar.gz').is_file():
            raise ValueError(f'Missing downloaded archive for {arxiv_id}')
        repairs[arxiv_id] = (folder, sources)
    if not repairs:
        raise ValueError('No repairs found')
    manifests = {}
    seen = set()
    for archive in archives:
        manifest_path = archive.with_name(archive.name.removesuffix('.tar.gz') + '.json')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if archive.stat().st_size != manifest.get('archive_bytes') or _sha256(archive) != manifest.get('archive_sha256'):
            raise ValueError(f'Checkpoint checksum mismatch: {archive}')
        ids = set(manifest['ids'])
        if ids & seen:
            raise ValueError(f'Overlapping IDs in {archive.name}')
        seen.update(ids)
        manifests[archive] = (manifest_path, manifest, ids & repairs.keys())
    if missing := repairs.keys() - seen:
        raise ValueError(f'Repairs not present in manifests: {sorted(missing)}')
    output_dir.mkdir(parents=True, exist_ok=True)
    affected = []
    for archive, (manifest_path, manifest, ids) in manifests.items():
        target = output_dir / archive.name
        if not ids:
            shutil.copy2(archive, target)
            shutil.copy2(manifest_path, output_dir / manifest_path.name)
            continue
        found = set()
        with tarfile.open(archive, 'r:gz') as source, tarfile.open(target, 'w:gz') as dest:
            for member in source:
                status_id = next((a for a in ids if member.name ==
                                  f'working/{folder_name_for_arxiv_id(a)}/status.json'), None)
                source_id = next((a for a in ids if member.name.startswith(
                                  f'working/{folder_name_for_arxiv_id(a)}/v1/sources/')), None)
                if source_id and member.isfile():
                    raise ValueError(f'{source_id} already has v1 sources in the checkpoint')
                if status_id:
                    with source.extractfile(member) as stream:
                        status = json.load(stream)
                    versions = [v for v in status.get('versions', []) if v.get('version') == 1]
                    if len(versions) != 1 or versions[0].get('status') != 'error':
                        raise ValueError(f'{status_id} is not a failed v1 record')
                    folder, files = repairs[status_id]
                    versions[0].update(status='ok', reason=None,
                                       filtered_bytes=sum(p.stat().st_size for p in files),
                                       file_count=len(files),
                                       files=[p.relative_to(folder / 'sources').as_posix() for p in files])
                    status.update(status='ok', error=None, recovered_from_source_archive=True)
                    data = (json.dumps(status, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                    updated = copy.copy(member)
                    updated.size = len(data)
                    dest.addfile(updated, io.BytesIO(data))
                    found.add(status_id)
                elif member.isfile():
                    with source.extractfile(member) as stream:
                        dest.addfile(member, stream)
                else:
                    dest.addfile(member)
            if found != ids:
                raise ValueError(f'Missing status for {sorted(ids - found)}')
            for arxiv_id in sorted(ids):
                folder, files = repairs[arxiv_id]
                for path in files:
                    rel = path.relative_to(folder / 'sources').as_posix()
                    dest.add(path, arcname=f'working/{folder_name_for_arxiv_id(arxiv_id)}/v1/sources/{rel}', recursive=False)
        updated_manifest = dict(manifest)
        updated_manifest['archive_bytes'] = target.stat().st_size
        updated_manifest['archive_sha256'] = _sha256(target)
        updated_manifest['ok'] = manifest.get('ok', 0) + len(ids)
        updated_manifest['failed'] = manifest.get('failed', 0) - len(ids)
        updated_manifest['filtered_source_bytes'] = manifest.get('filtered_source_bytes', 0) + sum(
            p.stat().st_size for a in ids for p in repairs[a][1])
        updated_manifest['repaired_ids'] = sorted(ids)
        write_json(output_dir / manifest_path.name, updated_manifest)
        affected.append({'batch': archive.name, 'ids': sorted(ids)})
    report = {'input': str(batch_dir), 'repairs': str(repairs_dir), 'repaired_batches': affected}
    write_json(output_dir / 'repair_log.json', report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-dir', type=Path, required=True)
    parser.add_argument('--repairs-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_repaired_checkpoints(args.batch_dir, args.repairs_dir, args.output_dir), ensure_ascii=False))


if __name__ == '__main__':
    main()
