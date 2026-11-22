"""Additional adversarial-ish static LaTeX regressions (synthetic fixtures)."""
from pathlib import Path
import pytest

from src.m2_parsing.gather import (
    active_tex, extract_include_targets, compilation_path,
    concatenate_compilation_tex, find_document_root, resolve_include_path,
)
from src.m2_parsing.pipeline import parse_one_version


def make_source(tmp_path: Path, files: dict[str, str]) -> Path:
    folder = tmp_path / '2603-12345' / 'v1' / 'sources'
    folder.mkdir(parents=True)
    for path, content in files.items():
        dest = folder / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding='utf-8')
    return folder


@pytest.mark.parametrize(('command','target'), [
    (r'\import{content/}{intro}', 'content/intro'),
    (r'\subimport{content/}{intro}', 'content/intro'),
    (r'\inputfrom{content/}{intro}', 'content/intro'),
    (r'\subinputfrom{content/}{intro}', 'content/intro'),
    (r'\includefrom{content/}{intro}', 'content/intro'),
    (r'\subincludefrom{content/}{intro}', 'content/intro'),
    (r'\subfile{content/intro}', 'content/intro'),
    (r'\input{content/intro}', 'content/intro'),
    (r'\include{content/intro}', 'content/intro'),
    (r'\input content/intro', 'content/intro'),
])
def test_supported_static_include_commands(tmp_path, command, target):
    root = make_source(tmp_path, {
        'main.tex': '\\documentclass{article}\\begin{document}' + command + '\\end{document}',
        'content/intro.tex': r'\section{Introduction}Actual scientific work.',
    })
    assert extract_include_targets(command) == [target]
    result = parse_one_version('2603.12345', 1, tmp_path)
    assert result.empty is False
    assert result.partial is False
    assert 'content/intro.tex' in result.compilation_files
    assert 'Actual scientific work.' in result.source_tex


@pytest.mark.parametrize('literal', [
    r'\begin{verbatim}\input{not-real}\end{verbatim}',
    r'\begin{Verbatim}\input{not-real}\end{Verbatim}',
    r'\begin{lstlisting}\input{not-real}\end{lstlisting}',
    r'\begin{minted}{latex}\input{not-real}\end{minted}',
    r'\begin{comment}\input{not-real}\end{comment}',
    r'\begin{filecontents}{generated.tex}\input{not-real}\end{filecontents}',
    r'\verb|\input{not-real}|',
    r'\verb*+\input{not-real}+',
])
def test_literal_tex_examples_are_not_followed(tmp_path, literal):
    root = make_source(tmp_path, {
        'main.tex': ('\\documentclass{article}\\begin{document}' + literal +
                     r'\section{Real}Only real content.\end{document}'),
        'not-real.tex': r'\section{Wrong}Unexpected!',
    })
    result = parse_one_version('2603.12345', 1, tmp_path)
    assert result.compilation_files == ['main.tex']
    assert not result.partial
    assert 'Unexpected!' not in result.source_tex
    assert 'Only real content.' in result.source_tex


def test_preserves_inline_include_order(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': (r'\documentclass{article}\begin{document}'
                     r'Before \input{part_a} between \import{parts/}{part_b} after'
                     r'\end{document}'),
        'part_a.tex': 'FIRST',
        'parts/part_b.tex': 'SECOND',
    })
    joined = concatenate_compilation_tex(s)
    assert joined.index('Before') < joined.index('FIRST') < joined.index('between')
    assert joined.index('between') < joined.index('SECOND') < joined.index('after')


def test_nested_relative_subimport(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{a/chapter}\end{document}',
        'a/chapter.tex': r'\subimport{sections/}{intro}',
        'a/sections/intro.tex': r'\section{Actual}Real.',
    })
    assert [p.relative_to(s).as_posix() for p in compilation_path(s)] == [
        'main.tex', 'a/chapter.tex', 'a/sections/intro.tex'
    ]


def test_comment_and_case_fallback_for_import(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': (r'\documentclass{article}' + '\n' +
                     r'% \import{lost/}{file}' + '\n' +
                     r'\begin{document}\import{Content/}{Intro}\end{document}'),
        'content/intro.tex': r'\section{Actual}Real.',
    })
    assert 'content/intro.tex' in [p.relative_to(s).as_posix() for p in compilation_path(s)]


def test_cycle_resolves_without_infinite_loop(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{a}\end{document}',
        'a.tex': r'\section{A}\input{b}',
        'b.tex': r'\section{B}\input{a}',
    })
    assert len(compilation_path(s)) == 3
    assert concatenate_compilation_tex(s).count(r'\section{A}') == 1


def test_binary_nonsense_does_not_create_tex_root(tmp_path):
    s = make_source(tmp_path, {'main.tex': '% \\documentclass{article}\n\\begin{verbatim}\\documentclass{article}\\end{verbatim}'})
    assert find_document_root(s) is None


def test_unresolved_include_gets_partial_not_silent_success(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\section{Intro}abc.\input{lost}\end{document}',
    })
    res = parse_one_version('2603.12345', 1, tmp_path)
    assert res.partial
    assert any('lost' in x for x in res.missing_includes)


def test_nontex_assets_do_not_get_included(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': r'\documentclass{article}\begin{document}\input{refs.bib}\section{Intro}abc.\end{document}',
        'refs.bib': 'stuff',
    })
    assert [p.name for p in compilation_path(s)] == ['main.tex']


def test_local_input_path_stays_inside_archive(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': (r'\documentclass{article}'
                     r'\def\input@path{{../../../../outside/}}'
                     r'\begin{document}\input{private}\end{document}'),
    })
    (tmp_path / 'outside').mkdir()
    (tmp_path / 'outside' / 'private.tex').write_text('SECRET')
    assert resolve_include_path(s, s / 'main.tex', 'private', ['../../../../outside']) is None


def test_subfiles_standalone_driver_is_not_root_or_body_break(tmp_path):
    s = make_source(tmp_path, {
        'main.tex': (r'\documentclass{article}\title{Research}'
                     r'\begin{document}\section{Summary}Main before. '
                     r'\subfile{chapters/chapter1} '
                     r'\section{Conclusion}Main after.\end{document}'),
        'chapters/chapter1.tex': (r'\documentclass[../main.tex]{subfiles}'
                                 r'\begin{document}\section{Experiments}Nested finding.'
                                 r'\end{document}'),
    })
    assert find_document_root(s).name == 'main.tex'
    res = parse_one_version('2603.12345', 1, tmp_path)
    assert not res.empty and not res.partial
    assert 'Nested finding.' in res.source_tex
    assert 'Main after.' in res.source_tex
    assert 'subfiles' not in res.source_tex
    assert 'Conclusion' in [n.content for n in res.tree.children if n.kind == 'heading'] or 'Conclusion' in res.source_tex


def test_dynamic_filename_is_visible_as_partial(tmp_path):
    make_source(tmp_path, {
        'main.tex': (r'\documentclass{article}\begin{document}'
                     r'\section{Intro}Real content.'
                     r'\input{\mychapterfile}\end{document}'),
    })
    res = parse_one_version('2603.12345', 1, tmp_path)
    assert res.partial
    assert any('dynamic' in missing for missing in res.missing_includes)
