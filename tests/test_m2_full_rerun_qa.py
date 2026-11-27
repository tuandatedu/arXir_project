"""Smoke/integrity tests for full rerun and master ZIP consolidation."""
from pathlib import Path
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from src.m2_parsing.batch_pipeline import PIPELINE_REVISION
from src.m2_parsing.quality_checks import (
    validate_metrics, validate_range_output, combine_verified_range_zips, verify_tables_zip
)


def make_valid(tmp_path: Path, n: int, arxiv_id: str):
    folder = tmp_path / f'range_{n}'
    folder.mkdir(parents=True)
    m = {
        'pipeline_revision': PIPELINE_REVISION,
        'n_publications': 1, 'n_versions_total': 1, 'n_versions_parsed': 1,
        'n_versions_empty': 0, 'n_versions_partial': 0, 'n_versions_failed': 0,
        'n_elements_before_dedup': 2, 'n_elements_after_dedup': 2,
        'n_bib_before': 1, 'n_bib_after': 1, 'n_hierarchy_edges': 1,
        'duration_sec': 0.1, 'output_bytes': 999, 'batch_count': 1,
        'coverage': [{
            'arxiv_id': arxiv_id, 'versions': [1], 'n_versions': 1,
            'parsed_versions': [1], 'empty_versions': [], 'failed_versions': [],
            'partial_versions': [], 'n_parsed': 1, 'n_empty': 0, 'n_failed': 0,
            'n_partial': 0, 'n_elements_after_dedup': 2, 'n_bib_after': 1,
            'n_elements_before_dedup': 2, 'n_bib_before': 1,
        }],
    }
    rows = {
        'elements': [
            {'arxiv_id': arxiv_id, 'element_id': f'{arxiv_id}#doc', 'kind': 'document', 'content': 'A'},
            {'arxiv_id': arxiv_id, 'element_id': f'{arxiv_id}#sent', 'kind': 'sentence', 'content': 'Sentence.'},
        ],
        'hierarchy': [{'arxiv_id': arxiv_id, 'version': 1, 'element_id': f'{arxiv_id}#sent',
                       'parent_id': f'{arxiv_id}#doc'}],
        'bibtex': [{'arxiv_id': arxiv_id, 'citation_key': 'foo', 'entry_type': 'article'}],
    }
    (folder / 'tables').mkdir()
    for name, values in rows.items():
        (folder / 'tables' / f'{name}.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in values))
    (folder / 'tables' / 'metrics_m2.json').write_text(json.dumps(m))
    archive = folder / f'M2_range_{n}_tables.zip'
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as z:
        for filename in ('elements.jsonl', 'hierarchy.jsonl', 'bibtex.jsonl', 'metrics_m2.json'):
            z.write(folder / 'tables' / filename, arcname=filename)
    return folder, archive, m


def test_qa_and_master_merge_clean_two_ranges(tmp_path):
    for n in (1, 2):
        folder, archive, m = make_valid(tmp_path, n, f'2310.{n:05d}')
        report = validate_range_output(folder / 'tables')
        assert report['passed']
        assert report['row_counts'] == {'elements': 2, 'hierarchy': 1, 'bibtex': 1}
        (folder / 'quality_report.json').write_text(json.dumps(report))
        verify_tables_zip(archive, m)
    result = tmp_path / 'master.zip'
    manifest = combine_verified_range_zips(tmp_path, [1, 2], result)
    assert manifest['n_publications'] == 2
    with ZipFile(result) as z:
        assert len(z.read('elements.jsonl').splitlines()) == 4
        assert len(z.read('hierarchy.jsonl').splitlines()) == 2
        assert len(z.read('bibtex.jsonl').splitlines()) == 2
        m = json.loads(z.read('metrics_m2.json'))
        assert m['n_publications'] == 2 and len(m['coverage']) == 2


def test_detect_missing_or_duplicate_papers(tmp_path):
    _, _, m = make_valid(tmp_path, 1, '2310.12345')
    with pytest.raises(ValueError, match='Manifest/coverage'):
        validate_metrics(m, expected_ids={'2310.12346'})
    with pytest.raises(ValueError, match='Duplicate'):
        validate_metrics({**m, 'coverage': m['coverage'] * 2, 'n_publications': 2})


def test_detect_truncated_elements_and_cross_range_overlap(tmp_path):
    folder, _, _ = make_valid(tmp_path, 1, '2310.12345')
    (folder / 'tables' / 'elements.jsonl').write_text('')
    with pytest.raises(ValueError, match='elements'):
        validate_range_output(folder / 'tables')
    for n in (2, 3):
        folder, _, _ = make_valid(tmp_path, n, '2310.98765')
        (folder / 'quality_report.json').write_text(json.dumps(validate_range_output(folder / 'tables')))
    with pytest.raises(ValueError, match='overlap'):
        combine_verified_range_zips(tmp_path, [2, 3], tmp_path / 'out.zip')


def test_stale_revision_and_broken_json_are_rejected(tmp_path):
    folder, _, m = make_valid(tmp_path, 1, '2310.12345')
    with pytest.raises(ValueError, match='revision'):
        validate_metrics({**m, 'pipeline_revision': PIPELINE_REVISION - 1})
    (folder / 'tables' / 'hierarchy.jsonl').write_text('{broken\n')
    with pytest.raises(ValueError, match='broken JSONL'):
        validate_range_output(folder / 'tables')


def test_trace_warnings_are_nonfatal(tmp_path):
    folder, _, m = make_valid(tmp_path, 1, '2310.12345')
    m['coverage'][0]['source_trace'] = [
        {'version': 1, 'root_file': 'template.tex', 'source_characters': 100}
    ]
    warnings = validate_metrics(m)
    assert not any('root possibly template' in msg for msg in warnings)
    assert any('short source' in msg for msg in warnings)
