"""Reuse only results tied to exact source, runtime code and output bytes."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

TABLE_FILES = ('elements.jsonl', 'hierarchy.jsonl', 'bibtex.jsonl')

def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[2]
    h = hashlib.sha256()
    runtime = {'python': sys.version, 'platform': os.name}
    for name in ('bibtexparser', 'pylatexenc', 'pyparsing'):
        runtime[name] = importlib.metadata.version(name)
    h.update(json.dumps(runtime, sort_keys=True).encode())
    files = [*root.joinpath('src/m2_parsing').glob('*.py'), *root.joinpath('src/common').glob('*.py'), root / 'src/m2_parsing/requirements.txt']
    for path in sorted(files):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(bytes.fromhex(digest_file(path)))
    return h.hexdigest()

def source_fingerprint(publication: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(Path(publication).rglob('*')):
        rel = path.relative_to(publication)
        # Only M1 inputs, excluding all parser-created raw/parsed files.
        allowed = (len(rel.parts) == 1 and path.name in ('paper.json', 'status.json')) or (
            rel.parts[0].startswith('v') and (
                (len(rel.parts) == 2 and path.name in ('metadata.json', 'status.json', 'empty.json'))
                or (len(rel.parts) >= 2 and rel.parts[1] == 'sources')))
        if path.is_dir() and len(rel.parts) == 1 and rel.parts[0].startswith('v'):
            h.update((rel.as_posix() + '/').encode())
        if allowed and path.is_file():
            h.update(rel.as_posix().encode())
            h.update(bytes.fromhex(digest_file(path)))
    return h.hexdigest()

def read_publication_cache(publication: Path, fingerprint: str):
    parsed = Path(publication) / 'parsed'
    try:
        receipt = json.loads((parsed / 'complete.json').read_text(encoding='utf8'))
        if receipt['code_fingerprint'] != fingerprint or receipt['source_fingerprint'] != source_fingerprint(publication): return None
        if receipt['coverage'].get('n_failed') or not receipt['coverage'].get('n_versions'): return None
        rows = {}
        for name in TABLE_FILES:
            path = parsed / name
            if digest_file(path) != receipt['output_sha256'][name]: return None
            rows[name.removesuffix('.jsonl')] = [json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()]
        return rows, receipt['coverage']
    except (OSError, ValueError, KeyError, TypeError):
        return None

def save_publication_cache(publication: Path, fingerprint: str, coverage: dict):
    if coverage.get('n_failed') or not coverage.get('n_versions'): return
    parsed = Path(publication) / 'parsed'
    receipt = {'code_fingerprint': fingerprint, 'source_fingerprint': source_fingerprint(publication),
               'coverage': coverage, 'output_sha256': {name: digest_file(parsed / name) for name in TABLE_FILES}}
    temp = parsed / 'complete.incomplete.json'
    temp.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf8')
    os.replace(temp, parsed / 'complete.json')
