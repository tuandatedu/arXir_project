"""Classify version-level outcomes using evidence, not filename heuristics.

M2 input may be absent (no LaTeX) and is deliberately SKIPPED, not counted as
an error. Partial static TeX parsing is a review state and never rewritten to
'clean' just to improve scores. Every version receives a machine-readable row.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path

# Only well-established external TeX support macros. Not proof they were harmless.
SUPPORT_INCLUDE = frozenset({
    "xy", "xypic", "epsf", "psfig", "glyphtounicode", "pdftexcmds",
    "epstopdf", "supp-pdf", "miniltx", "graphicx",
})
NO_LATEX_REASONS = frozenset({
    "empty record from M1", "missing sources directory", "no LaTeX files in source directory",
})


def _vers(entries):
    return {x if isinstance(x, int) else x.get('version'): x for x in entries}


def _include_basename(raw):
    name = raw.split(':', 1)[-1].strip().replace('\\', '/').split('/')[-1].lower()
    return name[:-4] if name.endswith('.tex') else name


def classify_coverage(metrics):
    records = []
    for paper in metrics['coverage']:
        pid = paper['arxiv_id']
        parsed, empty, partial, failed = (_vers(paper.get(k, [])) for k in (
            'parsed_versions', 'empty_versions', 'partial_versions', 'failed_versions'))
        traces = {t['version']: t for t in paper.get('source_trace', [])}
        if not paper.get('versions'):
            # Manifest may list a paper whose M1 checkpoint omitted its directory.
            # Do not invent v1; record the publication-level input skip separately.
            records.append({'arxiv_id': pid, 'version': None,
                            'status': 'SKIP_NO_M1_RECORD',
                            'reason': 'No version records supplied in M1 checkpoint',
                            'error': None, 'error_type': None, 'root_file': None,
                            'source_characters': 0, 'n_nodes': None, 'n_edges': None,
                            'missing_includes': [], 'unrepresented_headings': [], 'details': []})
        for version in paper.get('versions', []):
            src = traces.get(version, {})
            error_row = failed.get(version)
            error = error_row.get('error') if isinstance(error_row, dict) else None
            reason = src.get('reason') or error or ''
            headings = src.get('unrepresented_headings') or []
            includes = src.get('missing_includes') or []
            details = []
            if src.get('bibliography_review'):
                details.append({'type': 'REVIEW_BIBLIOGRAPHY_METADATA', 'evidence': src['bibliography_review']})
            if paper.get('unresolved_citation_keys'):
                details.append({'type': 'REVIEW_UNRESOLVED_CITATIONS', 'evidence': paper['unresolved_citation_keys']})
            if version in empty and reason in NO_LATEX_REASONS:
                status = 'SKIP_NO_LATEX'
            elif version in empty:
                status = 'SKIP_INPUT_EMPTY'
            elif version in failed:
                status = ('REVIEW_UNPARSEABLE_SOURCE'
                          if (reason.startswith('no \\documentclass root') or
                              reason == 'no parsed content in nonempty TeX source')
                          else 'PARSER_FAILED')
            elif version in partial:
                status = 'REVIEW_MISSING_INCLUDE'
            elif version in parsed:
                status = 'PARSED'
            else:
                status = 'REVIEW_UNCLASSIFIED'
            if headings:
                if all(re.search(r'#[1-9]', h) for h in headings):
                    details.append({'type': 'INFO_PLACEHOLDER_HEADING', 'evidence': headings})
                else:
                    details.append({'type': 'REVIEW_HEADING_MISMATCH', 'evidence': headings})
            if includes:
                if all(_include_basename(x) in SUPPORT_INCLUDE for x in includes):
                    details.append({'type': 'INFO_TEX_SUPPORT_INCLUDE', 'evidence': includes})
                    if status == 'REVIEW_MISSING_INCLUDE':
                        status = 'PARSED_WITH_SUPPORT_INCLUDE_WARNING'
                else:
                    details.append({'type': 'REVIEW_MISSING_INCLUDE', 'evidence': includes})
            if src.get('root_coverage_review'):
                details.append({
                    'type': 'REVIEW_ROOT_COVERAGE',
                    'evidence': {
                        'unused_tex_count': src.get('unused_tex_count', 0),
                        'unused_tex_bytes': src.get('unused_tex_bytes', 0),
                        'source_characters': src.get('source_characters', 0),
                        'included_files': src.get('included_files', []),
                    },
                })
            if status == 'PARSED' and any(x['type'].startswith('REVIEW_') for x in details):
                status = 'PARSED_NEEDS_REVIEW'
            # Source is very short: retain fact in diagnostic detail, not an error.
            chars = src.get('source_characters', 0)
            if src.get('root_file') and 0 < chars < 250:
                details.append({'type': 'INFO_SHORT_SOURCE', 'evidence': chars})
            row = {
                'arxiv_id': pid, 'version': version, 'status': status,
                'reason': reason, 'error': error, 'error_type': (
                    error_row.get('error_type') if isinstance(error_row, dict) else None),
                'root_file': src.get('root_file'),
                'source_characters': chars, 'n_nodes': src.get('n_nodes'),
                'n_edges': src.get('n_edges'), 'missing_includes': includes,
                'unrepresented_headings': headings, 'details': details,
            }
            records.append(row)
    return records


def save_diagnostics(metrics, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rows = classify_coverage(metrics)
    expected = metrics['n_versions_total']
    publication_only = sum(not p.get('versions') for p in metrics['coverage'])
    expected_records = expected + publication_only
    if (len(rows) != expected_records or
            len({(r['arxiv_id'], r['version']) for r in rows}) != expected_records):
        raise ValueError('Per-version and M1-missing-publication coverage incomplete or duplicated')
    with (dest / 'paper_status.jsonl').open('w', encoding='utf-8') as statuses, \
         (dest / 'issues.jsonl').open('w', encoding='utf-8') as issues:
        for row in rows:
            payload = json.dumps(row, ensure_ascii=False) + '\n'
            statuses.write(payload)
            if row['status'] != 'PARSED' or row['details']:
                issues.write(payload)
    summary = {
        'n_publications': metrics['n_publications'], 'n_versions': expected,
        'n_input_missing_publication_records': publication_only,
        'status_counts': dict(Counter(r['status'] for r in rows)),
        'classifications': {
            'SKIP_NO_LATEX': 'No usable LaTeX source in M1; not an M2 failure',
            'SKIP_NO_M1_RECORD': 'Paper ID existed in manifest, but no version record was supplied',
            'PARSER_FAILED': 'Actual parser or finalization exception; inspect parser_full.log',
            'REVIEW_UNPARSEABLE_SOURCE': 'LaTeX found, but no resolvable TeX root/content',
            'REVIEW_MISSING_INCLUDE': 'Unresolved include may hide body content',
            'PARSED_WITH_SUPPORT_INCLUDE_WARNING': 'Only known TeX support include unresolved; not proven harmless',
            'PARSED_NEEDS_REVIEW': 'Source headings or root coverage need manual inspection',
            'PARSED': 'Passed static parsing; not proof source compiles',
        },
        'warning_policy': 'Filename-only template/sample is never an error. Macro placeholders and system support are informational. No assertion of 0 false positives.',
    }
    (dest / 'status_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary
