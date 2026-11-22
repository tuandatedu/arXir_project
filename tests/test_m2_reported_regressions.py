"""Regression coverage for arXiv LaTeX root choice and include lookup.

The tests are synthetic reproductions of reported failure modes, not a claim
that the original archives 2603.27478 / 2603.16859 were available to inspect.
"""
from pathlib import Path
import pytest

from src.m2_parsing.gather import (
    compilation_path, concatenate_compilation_tex, extract_input_search_paths,
    find_document_root, resolve_include_path,
)
from src.m2_parsing.pipeline import parse_one_version


def source_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    s = tmp_path / '2603-12345' / 'v1' / 'sources'
    s.mkdir(parents=True)
    for name, text in files.items():
        file = s / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
    return s


def rel_paths(s: Path) -> list[str]:
    return [p.relative_to(s).as_posix() for p in compilation_path(s)]


def test_root_is_paper_not_template(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': (r'\documentclass{article}\begin{document}'
                     r'\section{Instructions}Replace all template text.'
                     r'\end{document}'),
        'submission.tex': (r'\documentclass{article}\begin{document}'
                           r'\title{Scientific Paper}\maketitle'
                           r'\section{Introduction}Here is the actual introduction.'
                           r'\section{Method}We evaluated our method.'
                           r'\end{document}'),
    })
    assert find_document_root(s).name == 'submission.tex'
    assert 'actual introduction' in concatenate_compilation_tex(s)
    assert 'Replace all template text' not in concatenate_compilation_tex(s)


def test_root_prefers_main_to_standalone_guide(tmp_path):
    s = source_dir(tmp_path, {
        'guide.tex': r'\documentclass{article}\begin{document}\section{Guide}How to use this template.\end{document}',
        'main.tex': r'\documentclass{article}\title{My Manuscript}\begin{document}\section{Results}Findings.\end{document}',
    })
    assert find_document_root(s).name == 'main.tex'


def test_include_respects_input_path(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': (r'\documentclass{article}'
                     r'\makeatletter\def\input@path{{content/}}\makeatother'
                     r'\begin{document}\input{intro}\end{document}'),
        'content/intro.tex': r'\section{Introduction}Actual body.',
    })
    assert 'content/intro.tex' in rel_paths(s)
    assert 'Actual body' in concatenate_compilation_tex(s)


def test_newcommand_multiple_search_paths(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': (r'\documentclass{article}'
                     r'\newcommand{\input@path}{{prelude/}{content/}}'
                     r'\begin{document}\input{intro}\end{document}'),
        'content/intro.tex': r'\section{Introduction}Content directory.',
    })
    assert extract_input_search_paths((s / 'main.tex').read_text()) == ['prelude/', 'content/']
    assert 'content/intro.tex' in rel_paths(s)


def test_search_path_declared_in_reachable_nested_file(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': (r'\documentclass{article}'
                     r'\begin{document}\input{preamble}\input{intro}\end{document}'),
        'preamble.tex': r'\makeatletter\gdef\input@path{{content/}}\makeatother',
        'content/intro.tex': r'\section{Introduction}Nested body.',
    })
    assert rel_paths(s) == ['main.tex', 'preamble.tex', 'content/intro.tex']
    assert 'Nested body' in concatenate_compilation_tex(s)


def test_commented_search_path_is_ignored(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': (r'\documentclass{article}' '\n'
                     r'% \def\input@path{{content/}}' '\n'
                     r'\begin{document}\input{intro}\end{document}'),
        'content/intro.tex': 'Text',
    })
    assert rel_paths(s) == ['main.tex']


def test_include_case_fallback(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{Content/Intro}\end{document}',
        'content/intro.tex': r'\section{Introduction}Actual body.',
    })
    assert 'content/intro.tex' in rel_paths(s)
    assert 'Actual body' in concatenate_compilation_tex(s)


def test_exact_match_wins_before_case_fallback(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{content/intro}\end{document}',
        'content/intro.tex': r'\section{Correct}Exact path.',
        'Content/Intro.tex': r'\section{Incorrect}Wrong path.',
    })
    assert rel_paths(s) == ['main.tex', 'content/intro.tex']


def test_ambiguous_case_fallback_is_not_guessed(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{INTRO}\end{document}',
        'intro.tex': 'One',
        'Intro.tex': 'Two',
    })
    if len([p for p in s.iterdir() if p.name.casefold() == 'intro.tex']) != 2:
        pytest.skip('This test needs a filesystem that can store intro.tex and Intro.tex separately')
    assert resolve_include_path(s, s / 'main.tex', 'INTRO') is None


def test_paths_cannot_escape_source_directory(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{../../../outside}\end{document}',
    })
    (tmp_path / 'outside.tex').write_text('Outside data', encoding='utf-8')
    assert resolve_include_path(s, s / 'main.tex', '../../../outside') is None


def test_full_version_parse_retains_included_sections(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': (r'\documentclass{article}\makeatletter'
                     r'\def\input@path{{content/}}\makeatother'
                     r'\begin{document}\title{Research}\maketitle'
                     r'\input{intro}\input{Method}\end{document}'),
        'content/intro.tex': r'\section{Introduction}The introduction has findings.',
        'content/method.tex': r'\section{Methodology}The model has a method.',
    })
    result = parse_one_version('2603.12345', 1, working_dir=tmp_path)
    assert not result.empty
    assert not result.partial
    assert result.missing_includes == []
    assert set(result.compilation_files) == {'main.tex', 'content/intro.tex', 'content/method.tex'}
    assert 'The introduction has findings' in result.source_tex
    assert 'The model has a method' in result.source_tex


def test_explicit_include_baseline(tmp_path):
    s = source_dir(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{content/intro}\end{document}',
        'content/intro.tex': r'\section{Introduction}Actual body.',
    })
    assert 'content/intro.tex' in rel_paths(s)
