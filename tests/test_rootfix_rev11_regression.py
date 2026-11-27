"""Reproduce six confirmed root-selection failure shapes from repaired M1 evidence.

Fixtures use the same file structure and include relationships as the audited
papers, not private M1 archives. They verify the selection and body inclusion.
"""
from pathlib import Path
import pytest

from src.m2_parsing.gather import find_document_root
from src.m2_parsing.pipeline import parse_one_version


def make_source(tmp_path: Path, files: dict[str, str]) -> Path:
    directory = tmp_path / 'working' / '2603-12345' / 'v1' / 'sources'
    directory.mkdir(parents=True)
    for name, contents in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf8')
    return directory


@pytest.mark.parametrize('paper, files, expected', [
    ('2609.38910', {
        'preamble-oren.tex': r'\documentclass{article}',
        'main.tex': r'\input{preamble-oren}\begin{document}\input{main-paper}\end{document}',
        'main-paper.tex': r'\input{sections/intro}\input{sections/method}',
        'sections/intro.tex': r'\section{Introduction}Actual work.',
        'sections/method.tex': r'\section{Method}Actual method.',
    }, 'main.tex'),
    ('2609.40278', {
        'preamble-oren.tex': r'\documentclass{article}',
        'main.tex': r'\input{preamble-oren}\begin{document}\input{main-paper}\end{document}',
        'main-paper.tex': r'\input{abstract}\input{intro/intro}\input{main-results}',
        'abstract.tex': 'Abstract body.',
        'intro/intro.tex': r'\section{Introduction}Actual work.',
        'main-results.tex': r'\section{Results}Interesting results.',
    }, 'main.tex'),
    ('2610.00697', {
        'Conferences/FullVersion/fullversion.tex': r'\documentclass{article}',
        'preamble.tex': r'\input{Conferences/FullVersion/fullversion}',
        'main.tex': r'\input{preamble}\begin{document}\input{Sections/all}\end{document}',
        'Sections/all.tex': r'\input{Sections/introduction}\input{Sections/results}',
        'Sections/introduction.tex': r'\section{Introduction}Real intro.',
        'Sections/results.tex': r'\section{Results}Real findings.',
    }, 'main.tex'),
    ('2604.18225', {
        'backup/main.tex': (r'\documentclass{article}\begin{document}'
                            r'\input{intro}\input{method}\end{document}'),
        'ICIP.tex': (r'\documentclass{article}\begin{document}'
                     r'\input{section/intro}\input{section/method}'
                     r'\input{section/experiments}\end{document}'),
        'section/intro.tex': r'\section{Introduction}Body.',
        'section/method.tex': r'\section{Method}Method.',
        'section/experiments.tex': r'\section{Experiments}Results.',
    }, 'ICIP.tex'),
    ('2604.15963', {
        'lib/xlistings/xlistings-doc.tex': (r'\documentclass{article}\begin{document}'
                                           r'\section{Library Documentation}Description.'
                                           r'\end{document}'),
        'fse-2026-tool.tex': (r'\documentclass{article}\begin{document}'
                             r'\input{segments/introduction}\input{segments/evaluation}'
                             r'\end{document}'),
        'segments/introduction.tex': r'\section{Introduction}New research.',
        'segments/evaluation.tex': r'\section{Evaluation}Experiments.',
    }, 'fse-2026-tool.tex'),
    ('2604.19976', {
        'paper_prefix.tex': r'\documentclass{article}\begin{document}',
        'paper_suffix.tex': r'\end{document}',
        'main.tex': (r'\input{paper_prefix}\input{sections/introduction}'
                     r'\input{sections/training}\input{sections/evaluation}'
                     r'\input{paper_suffix}'),
        'sections/introduction.tex': r'\section{Introduction}Research work.',
        'sections/training.tex': r'\section{Training}Details.',
        'sections/evaluation.tex': r'\section{Evaluation}Results.',
    }, 'main.tex'),
])
def test_confirmed_root_failures(paper, files, expected, tmp_path):
    source = make_source(tmp_path, files)
    chosen = find_document_root(source)
    assert chosen.relative_to(source).as_posix() == expected, paper
    parsed = parse_one_version('2603.12345', 1, tmp_path / 'working')
    assert parsed.compilation_files[0] == expected
    assert not parsed.missing_includes
    assert len(parsed.compilation_files) >= 3
    assert parsed.source_heading_count >= 2
    assert not parsed.empty


def test_commented_root_candidate_not_promoted(tmp_path):
    source = make_source(tmp_path, {
        'example.tex': r'% \documentclass{article}\begin{document}\end{document}',
        'main.tex': r'\documentclass{article}\begin{document}\section{Real}Real.\end{document}',
    })
    assert find_document_root(source).name == 'main.tex'


def test_short_parsed_root_with_many_unused_files_needs_review(tmp_path):
    from src.m2_parsing.diagnostics import classify_coverage
    source = make_source(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}Very short body.\end{document}',
        **{f'parts/part_{n}.tex': r'\section{Work}Research body.' * 30 for n in range(6)},
    })
    result = parse_one_version('2603.12345', 1, tmp_path / 'working')
    assert result.root_coverage_review
    paper = {
        'arxiv_id': '2603.12345', 'versions': [1],
        'parsed_versions': [1], 'empty_versions': [],
        'partial_versions': [], 'failed_versions': [],
        'source_trace': [{
            'version': 1, 'root_file': result.compilation_files[0],
            'included_files': result.compilation_files,
            'unused_tex_count': len(result.unused_files),
            'unused_tex_bytes': result.unused_tex_bytes,
            'source_characters': len(result.source_tex),
            'root_coverage_review': result.root_coverage_review,
            'unrepresented_headings': [], 'missing_includes': [],
        }],
    }
    row = classify_coverage({'coverage': [paper]})[0]
    assert row['status'] == 'PARSED_NEEDS_REVIEW'
    assert any(item['type'] == 'REVIEW_ROOT_COVERAGE' for item in row['details'])
