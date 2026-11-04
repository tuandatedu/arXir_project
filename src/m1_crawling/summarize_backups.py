"""Aggregate completed batch manifests and metadata JSONL for other teammates.

Does not extract the giant TeX corpus; reads two JSONL members per .tar.gz.
Run only after relevant batches have finished. Copies remain outside Git.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tarfile


def summarize(backup_dir: Path, output_dir: Path) -> dict:
    backup_dir, output_dir = Path(backup_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = sorted(backup_dir.glob('batch_*.json'))
    if not manifest_files:
        raise ValueError(f'No batch manifests in {backup_dir}')
    summary = {'batch_count': 0, 'assigned_ids': 0, 'ok': 0, 'no_tex': 0,
               'not_found': 0, 'failed': 0, 'archive_bytes': 0,
               'metadata_rows': 0, 'crawl_record_rows': 0,
               'runtime_seconds_sum_per_batch': 0.0,
               'discovery_seconds_sum_per_batch': 0.0,
               'input_archive_bytes': 0, 'filtered_source_bytes': 0,
               'warning': ('Per-batch runtimes are for the last run of each batch; '
                           'retries, sessions and Drive transfers are not represented '
                           'in end-to-end wall time.')}
    seen_ids: set[str] = set()
    with ((output_dir / 'papers.jsonl').open('w', encoding='utf-8') as papers_out,
          (output_dir / 'crawl_records.jsonl').open('w', encoding='utf-8') as records_out):
        for file in manifest_files:
            data = json.loads(file.read_text(encoding='utf-8'))
            archive = backup_dir / (file.stem + '.tar.gz')
            if not archive.is_file() or data.get('archive_bytes') != archive.stat().st_size:
                raise ValueError(f'Archive missing or size mismatch: {archive}')
            ids = data['ids']
            duplicates = seen_ids.intersection(ids)
            if duplicates:
                raise ValueError(f'Overlapping IDs in batches: {list(duplicates)[:4]}')
            seen_ids.update(ids)
            with tarfile.open(archive, 'r:gz') as tf:
                for member_name, output, counter in (
                    ('papers.jsonl', papers_out, 'metadata_rows'),
                    ('crawl_records.jsonl', records_out, 'crawl_record_rows'),
                ):
                    member = tf.extractfile(member_name)
                    if member is None:
                        raise ValueError(f'{member_name} missing in {archive}')
                    for line in member:
                        if line.strip():
                            # Validate JSONL rather than blind concatenate.
                            json.loads(line)
                            output.write(line.decode('utf-8'))
                            summary[counter] += 1
            summary['batch_count'] += 1
            summary['assigned_ids'] += len(ids)
            for field in ('ok', 'no_tex', 'not_found', 'failed', 'archive_bytes',
                          'input_archive_bytes', 'filtered_source_bytes'):
                summary[field] += data.get(field, 0)
            summary['runtime_seconds_sum_per_batch'] += data.get('runtime_seconds_this_run', 0)
            summary['discovery_seconds_sum_per_batch'] += data.get('discovery_seconds_this_run', 0)
    (output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                              encoding='utf-8')
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backup-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(summarize(args.backup_dir, args.output_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
