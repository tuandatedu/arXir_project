"""Fail-fast, streaming QA for rerunning and consolidating M2 range outputs.

This verifies output structure and statistical consistency, not that the
LaTeX compiled semantically. The latter still needs selected human inspection.
"""
from __future__ import annotations

from collections import Counter
from itertools import groupby
import hashlib
import json
from pathlib import Path
import shutil
from typing import Iterable
from zipfile import ZipFile, ZIP_DEFLATED

from src.common.ids import normalize_arxiv_id
from src.common.schemas import ELEMENT_KINDS, BIBTEX_ENTRY_TYPES
from .batch_pipeline import PIPELINE_REVISION, discover_checkpoint_batches

_TABLE_NAMES = ('elements', 'hierarchy', 'bibtex')
_COUNTS = {'elements': 'n_elements_after_dedup',
           'hierarchy': 'n_hierarchy_edges', 'bibtex': 'n_bib_after'}
_STATUS_MAP = {'parsed_versions': 'n_parsed', 'empty_versions': 'n_empty',
               'failed_versions': 'n_failed', 'partial_versions': 'n_partial'}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_metrics(metrics: dict, expected_ids: set[str] | None = None,
                     expected_revision: int = PIPELINE_REVISION) -> list[str]:
    """Reject duplicate coverage, version/status inconsistencies and stale parser."""
    if metrics.get('pipeline_revision') != expected_revision:
        raise ValueError(f"Parser revision mismatch: {metrics.get('pipeline_revision')} != {expected_revision}")
    coverage = metrics.get('coverage')
    if not isinstance(coverage, list):
        raise ValueError('Missing metrics.coverage')
    ids = [item.get('arxiv_id') for item in coverage]
    if any(not isinstance(id_, str) for id_ in ids) or len(set(ids)) != len(ids):
        raise ValueError('Duplicate or malformed arxiv_id in coverage')
    if expected_ids is not None and set(ids) != set(expected_ids):
        missing, extra = expected_ids - set(ids), set(ids) - expected_ids
        raise ValueError(f'Manifest/coverage disagreement: missing={len(missing)}, extra={len(extra)}')
    if metrics.get('n_publications') != len(coverage):
        raise ValueError('n_publications differs from coverage length')
    summary_fields = ('n_versions_total', 'n_versions_parsed', 'n_versions_empty',
                      'n_versions_failed', 'n_versions_partial',
                      'n_elements_after_dedup', 'n_bib_after')
    for field in summary_fields:
        row_field = {'n_versions_total': 'n_versions',
                     'n_versions_parsed': 'n_parsed',
                     'n_versions_empty': 'n_empty',
                     'n_versions_failed': 'n_failed',
                     'n_versions_partial': 'n_partial'} .get(field, field)
        if metrics.get(field) != sum(item.get(row_field, 0) for item in coverage):
            raise ValueError(f'{field} disagrees with coverage totals')
    warnings: list[str] = []
    for item in coverage:
        id_ = item['arxiv_id']
        versions = item.get('versions', [])
        if len(versions) != item.get('n_versions') or len(set(versions)) != len(versions):
            raise ValueError(f'{id_}: duplicate/incorrect version count')
        checked: list[int] = []
        for key, count_key in _STATUS_MAP.items():
            entries = item.get(key, [])
            if not isinstance(entries, list) or len(entries) != item.get(count_key):
                raise ValueError(f'{id_}: invalid {key} count')
            checked.extend((entry if isinstance(entry, int) else entry.get('version')) for entry in entries)
        if set(checked) != set(versions) or len(checked) != len(versions):
            raise ValueError(f'{id_}: missing or overlapping version statuses')
        if not versions:
            warnings.append(f'{id_}: no versions in M1 checkpoint')
        if item.get('n_partial') or item.get('n_failed'):
            warnings.append(f'{id_}: partial={item.get("n_partial")}, failed={item.get("n_failed")}')
        trace = item.get('source_trace', [])
        for detail in trace:
            root = detail.get('root_file') or ''
            # The filename 'template/sample' is not evidence of wrong document.
            # It may be the genuine main file, so do not raise a QA warning.
            if detail.get('root_file') and detail.get('source_characters', 0) < 250:
                warnings.append(f'{id_} v{detail.get("version")}: suspiciously short source')
            if detail.get('root_coverage_review'):
                warnings.append(f'{id_} v{detail.get("version")}: '
                                'potentially incomplete root (unused TeX body candidate)')
            unrepresented = detail.get('unrepresented_headings') or []
            if unrepresented:
                warnings.append(f'{id_} v{detail.get("version")}: {len(unrepresented)} '
                                f'unrepresented source headings, e.g. {unrepresented[:3]}')
        if item.get('n_elements_after_dedup', 0) <= 10 and item.get('n_parsed', 0) > 0:
            warnings.append(f'{id_}: only {item.get("n_elements_after_dedup")} elements')
    return warnings


def _check_hierarchy_foreign_keys(tables_dir: Path, valid_versions: dict[str, set[int]]) -> int:
    """Streaming publication-scoped foreign key validation.

    Each publication's elements and hierarchy are emitted consecutively by
    M2. Holding only a single publication's IDs avoids retaining millions of
    string IDs in memory. Check both ID membership and version membership.
    """
    def groups(table: str):
        with (tables_dir / f'{table}.jsonl').open(encoding='utf-8') as source:
            def rows():
                for line in source:
                    if line.strip():
                        yield json.loads(line)
            for arxiv_id, group in groupby(rows(), key=lambda row: row['arxiv_id']):
                yield arxiv_id, list(group)

    elements = iter(groups('elements'))
    current = next(elements, None)
    checked = 0
    seen_pubs: set[str] = set()
    for paper_id, rows in groups('hierarchy'):
        if paper_id in seen_pubs:
            raise ValueError(f'{paper_id}: hierarchy rows are not grouped by publication')
        seen_pubs.add(paper_id)
        while current is not None and current[0] != paper_id:
            current = next(elements, None)
        if current is None:
            raise ValueError(f'{paper_id}: hierarchy references missing publication elements')
        ids = [row['element_id'] for row in current[1]]
        allowed = set(ids)
        if len(allowed) != len(ids):
            raise ValueError(f'{paper_id}: duplicate element_id in elements table')
        for row in rows:
            if row['element_id'] not in allowed or row['parent_id'] not in allowed:
                raise ValueError(f'{paper_id}: broken hierarchy foreign key: {row}')
            if row['version'] not in valid_versions.get(paper_id, set()):
                raise ValueError(f'{paper_id}: hierarchy references nonexistent version {row["version"]}')
            checked += 1
        current = next(elements, None)
    return checked


def _semantic_review(coverage: list[dict]) -> tuple[list[dict], dict]:
    """Report every suspicious source version; do not truncate to 250 warnings."""
    reviews: list[dict] = []
    counts = Counter()
    for paper in coverage:
        if paper.get('unresolved_citation_keys'):
            counts['unresolved_citation_keys'] += 1
            reviews.append({'arxiv_id': paper['arxiv_id'], 'version': None,
                            'reasons': ['unresolved_citation_keys'],
                            'unresolved_citation_keys': paper['unresolved_citation_keys'],
                            'unrepresented_headings': [], 'missing_includes': []})
        statuses = {}
        for status in ('failed_versions', 'partial_versions', 'empty_versions'):
            for item in paper.get(status, []):
                v = item if isinstance(item, int) else item.get('version')
                statuses.setdefault(v, []).append(status)
        traced_versions = {trace.get('version') for trace in paper.get('source_trace', [])}
        for version_status in paper.get('failed_versions', []):
            version = (version_status if isinstance(version_status, int)
                       else version_status.get('version'))
            if version not in traced_versions:
                counts['parser_exception_without_source_trace'] += 1
                reviews.append({
                    'arxiv_id': paper['arxiv_id'], 'version': version,
                    'reasons': ['parser_exception_without_source_trace'],
                    'status': ['failed_versions'], 'root_file': None,
                    'error': version_status.get('error', '') if isinstance(version_status, dict) else '',
                    'missing_includes': [], 'unrepresented_headings': [],
                })
        for trace in paper.get('source_trace', []):
            version = trace.get('version')
            root = trace.get('root_file') or ''
            reasons = []
            if trace.get('bibliography_review'):
                reasons.append('bibliography_metadata_review')
            if trace.get('unrepresented_headings'):
                reasons.append('unrepresented_headings')
            if trace.get('missing_includes'):
                reasons.append('missing_includes')
            if trace.get('root_coverage_review'):
                reasons.append('root_coverage_review')
            # Never flag a suspected template solely from a root filename.
            if root and trace.get('source_characters', 0) < 250:
                reasons.append('very_short_source')
            # Missing input was recorded as SKIP_NO_LATEX, not M2 semantic error.
            if trace.get('reason') == 'no parsed content in nonempty TeX source':
                reasons.append('empty_parsing_from_nonempty_source')
            if not reasons:
                continue
            for reason in reasons:
                counts[reason] += 1
            reviews.append({
                'arxiv_id': paper['arxiv_id'], 'version': version,
                'reasons': reasons, 'status': statuses.get(version, ['parsed']),
                'root_file': root or None,
                'missing_includes': trace.get('missing_includes', []),
                'unrepresented_headings': trace.get('unrepresented_headings', []),
                'source_characters': trace.get('source_characters', 0),
                'unused_tex_count': trace.get('unused_tex_count', 0),
                'unused_tex_bytes': trace.get('unused_tex_bytes', 0),
                'bibliography_review': trace.get('bibliography_review', []),
            })
    return reviews, dict(counts)


def validate_range_output(tables_dir: Path, checkpoint_dir: Path | None = None,
                          *, check_rows: bool = True) -> dict:
    """Verify all JSONL rows, counts, membership, schema and checkpoint coverage."""
    tables_dir = Path(tables_dir)
    m = json.loads((tables_dir / 'metrics_m2.json').read_text(encoding='utf-8'))
    expected_ids = None
    if checkpoint_dir is not None:
        found = discover_checkpoint_batches(Path(checkpoint_dir))
        expected_ids = {normalize_arxiv_id(v) for _, _, manifest in found for v in manifest['ids']}
    warnings = validate_metrics(m, expected_ids)
    allowed = set(expected_ids or (row['arxiv_id'] for row in m['coverage']))
    counts: dict[str, int] = {}
    per_pub = {name: Counter() for name in ('elements', 'bibtex')}
    for name in _TABLE_NAMES:
        path = tables_dir / f'{name}.jsonl'
        if not path.is_file():
            raise FileNotFoundError(path)
        if not check_rows:
            counts[name] = None
            continue
        number = 0
        with path.open('r', encoding='utf-8') as source:
            for number, line in enumerate(source, 1):
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise ValueError(f'{path}:{number}: broken JSONL') from exc
                if not isinstance(row, dict) or row.get('arxiv_id') not in allowed:
                    raise ValueError(f'{path}:{number}: invalid or unrecognized arxiv_id')
                if name == 'elements':
                    if (row.get('kind') not in ELEMENT_KINDS or
                            not isinstance(row.get('content'), str) or
                            not isinstance(row.get('element_id'), str) or
                            not row['element_id']):
                        raise ValueError(f'{path}:{number}: invalid element')
                    per_pub[name][row['arxiv_id']] += 1
                elif name == 'hierarchy':
                    if (not isinstance(row.get('version'), int) or row['version'] < 1 or
                            not row.get('parent_id') or not row.get('element_id') or
                            row['element_id'] == row['parent_id']):
                        raise ValueError(f'{path}:{number}: invalid hierarchy edge')
                else:
                    if (row.get('entry_type') not in BIBTEX_ENTRY_TYPES or
                            not isinstance(row.get('citation_key'), str) or
                            not row['citation_key']):
                        raise ValueError(f'{path}:{number}: invalid bibtex entry')
                    per_pub[name][row['arxiv_id']] += 1
        counts[name] = number
        if counts[name] != m[_COUNTS[name]]:
            raise ValueError(f'{name}: {counts[name]} rows != metrics {_COUNTS[name]}={m[_COUNTS[name]]}')
    if check_rows:
        for row in m['coverage']:
            arxiv_id = row['arxiv_id']
            for name, metric_key in (('elements', 'n_elements_after_dedup'), ('bibtex', 'n_bib_after')):
                if per_pub[name][arxiv_id] != row.get(metric_key, 0):
                    raise ValueError(f'{arxiv_id} {name}: rows and per-paper coverage disagree')
    checked_edges = _check_hierarchy_foreign_keys(
        tables_dir, {row['arxiv_id']: set(row['versions']) for row in m['coverage']}
    ) if check_rows else None
    if check_rows and checked_edges != counts['hierarchy']:
        raise ValueError('hierarchy foreign key audit did not visit all edges')
    reviews, review_counts = _semantic_review(m['coverage'])
    if check_rows:
        review_path = tables_dir / 'semantic_review.jsonl'
        with review_path.open('w', encoding='utf-8') as sink:
            for review in reviews:
                sink.write(json.dumps(review, ensure_ascii=False) + '\n')
    heading_reviews = [
        {'arxiv_id': row['arxiv_id'], 'version': row['version'],
         'headings': row['unrepresented_headings']}
        for row in reviews if 'unrepresented_headings' in row['reasons']
    ]
    return {
        'passed': True, 'pipeline_revision': PIPELINE_REVISION,
        'n_publications': m['n_publications'],
        'source_heading_review_count': len(heading_reviews),
        'source_heading_review_sample': heading_reviews[:100],
        'semantic_review_count': len(reviews),
        'semantic_review_reasons': review_counts,
        'needs_content_review': bool(reviews),
        'semantic_review_file': 'semantic_review.jsonl',
        'hierarchy_foreign_keys_checked': checked_edges,
        'row_counts': counts, 'warnings_count': len(warnings),
        'warnings_sample': warnings[:250],
        'status_counts': {key: m[key] for key in (
            'n_versions_parsed', 'n_versions_empty', 'n_versions_failed', 'n_versions_partial')},
        'note': ('Integrity passed; semantic review is a separate status. '
                 'Source-level static parsing cannot certify 100% TeX correctness.'),
    }


def verify_tables_zip(archive: Path, expected_metrics: dict | None = None) -> None:
    """Check ZIP CRC and exact four expected files (all tables may be empty)."""
    with ZipFile(archive, 'r') as zipped:
        wanted = {*(f'{name}.jsonl' for name in _TABLE_NAMES), 'metrics_m2.json'}
        if set(zipped.namelist()) != wanted:
            raise ValueError(f'M2 ZIP members differ: {set(zipped.namelist()) ^ wanted}')
        failed = zipped.testzip()
        if failed:
            raise IOError(f'ZIP CRC verification failed for {failed}')
        if expected_metrics is not None:
            actual = json.loads(zipped.read('metrics_m2.json'))
            if actual != expected_metrics:
                raise ValueError('Metrics inside ZIP differ from disk metrics')


def combine_verified_range_zips(range_dir: Path, ranges: Iterable[int], output: Path) -> dict:
    """Combine clean, same-revision range zips into one streaming master ZIP.

    Call only after per-range checks; checks all IDs and version status coverage
    again so a mixed/partial rerun cannot be quietly published as master.
    """
    range_dir = Path(range_dir)
    ranges = list(ranges)
    if len(ranges) != len(set(ranges)) or not ranges:
        raise ValueError('Duplicate/empty range list')
    inputs = []
    seen_ids = set()
    for n in ranges:
        folder = range_dir / f'range_{n}'
        path = folder / f'M2_range_{n}_tables.zip'
        qa_path = folder / 'quality_report.json'
        if not qa_path.is_file():
            raise ValueError(f'Missing quality_report.json (rerun first): {folder}')
        qa = json.loads(qa_path.read_text(encoding='utf-8'))
        if not qa.get('passed') or qa.get('pipeline_revision') != PIPELINE_REVISION:
            raise ValueError(f'Range {n} was not QA-verified with current parser')
        verify_tables_zip(path)
        with ZipFile(path) as zipped:
            m = json.loads(zipped.read('metrics_m2.json'))
        validate_metrics(m)
        ids = {row['arxiv_id'] for row in m['coverage']}
        if seen_ids.intersection(ids):
            raise ValueError(f'Ranges overlap in arxiv_id: {n} shares {len(seen_ids.intersection(ids))} papers')
        seen_ids.update(ids)
        inputs.append((n, path, m))
    sum_fields = ('n_publications', 'n_versions_total', 'n_versions_parsed',
                  'n_versions_empty', 'n_versions_failed', 'n_versions_partial',
                  'n_elements_before_dedup', 'n_elements_after_dedup',
                  'n_bib_before', 'n_bib_after', 'n_hierarchy_edges', 'output_bytes',
                  'duration_sec', 'batch_count')
    merged = {key: sum(m.get(key, 0) for _, _, m in inputs) for key in sum_fields}
    merged['coverage'] = [item for _, _, m in inputs for item in m['coverage']]
    merged['normalized'] = True
    merged['pipeline_revision'] = PIPELINE_REVISION
    merged['selected_ranges'] = ranges
    merged['version_success_rate'] = (merged['n_versions_parsed'] / merged['n_versions_total']
                                      if merged['n_versions_total'] else 0)
    merged['peak_rss_bytes'] = max((m.get('peak_rss_bytes') or 0 for _, _, m in inputs), default=0)
    manifest = {
        'pipeline_revision': PIPELINE_REVISION, 'included_ranges': ranges,
        'range_zip_sha256': {f'range_{n}': sha256_file(path) for n, path, _ in inputs},
        'n_publications': len(seen_ids), 'version_status_counts': {
            k: merged[k] for k in ('n_versions_parsed', 'n_versions_partial',
                                   'n_versions_failed', 'n_versions_empty')},
        'limitations': 'Static LaTeX parsing; original source-level validation still recommended',
    }
    validate_metrics(merged, seen_ids)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=2, allowZip64=True) as result:
        for name in _TABLE_NAMES:
            with result.open(f'{name}.jsonl', 'w', force_zip64=True) as target:
                for _, input_path, _ in inputs:
                    with ZipFile(input_path) as zipped:
                        with zipped.open(f'{name}.jsonl') as source:
                            shutil.copyfileobj(source, target, length=8*1024*1024)
        result.writestr('metrics_m2.json', json.dumps(merged, ensure_ascii=False))
        result.writestr('master_manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(output) as result:
        failed = result.testzip()
        if failed:
            raise IOError(f'Master ZIP CRC failed: {failed}')
    return manifest
