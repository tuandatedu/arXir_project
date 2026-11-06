"""A recovered source remains available when its checkpoint is restored."""
import hashlib
import io
import json
import tarfile

from src.m2_parsing.archive_input import restore_batch
from src.m2_parsing.repair_checkpoints import build_repaired_checkpoints


def test_repair_preserves_original_and_rebuilds_valid_checkpoint(tmp_path):
    batches = tmp_path / 'original'
    batches.mkdir()
    archive = batches / 'batch_00000.tar.gz'
    status = {'arxiv_id': '2310.12345', 'status': 'error', 'error': 'too large',
              'versions': [{'version': 1, 'status': 'error', 'reason': 'too large'}]}
    payload = json.dumps(status).encode()
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo('working/2310-12345/status.json')
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    original_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = {'ids': ['2310.12345'], 'archive_bytes': archive.stat().st_size,
                'archive_sha256': original_sha, 'ok': 0, 'failed': 1}
    (batches / 'batch_00000.json').write_text(json.dumps(manifest), encoding='utf-8')
    repairs = tmp_path / 'repairs' / '2310-12345'
    (repairs / 'sources').mkdir(parents=True)
    (repairs / 'sources' / 'main.tex').write_text(r'\documentclass{article}', encoding='utf-8')
    (repairs / 'source.tar.gz').write_bytes(b'original source')
    target = tmp_path / 'repaired'
    report = build_repaired_checkpoints(batches, repairs.parent, target)
    assert report['repaired_batches'][0]['ids'] == ['2310.12345']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_sha
    restore_batch(target / archive.name, tmp_path / 'working')
    pub = tmp_path / 'working' / '2310-12345'
    assert (pub / 'v1' / 'sources' / 'main.tex').is_file()
    restored_status = json.loads((pub / 'status.json').read_text(encoding='utf-8'))
    assert restored_status['status'] == 'ok' and restored_status['versions'][0]['status'] == 'ok'
