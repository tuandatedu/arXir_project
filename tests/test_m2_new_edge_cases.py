"""More regression tests based on range_2 M1 sources."""
from src.m2_parsing.gather import find_document_root
from src.m2_parsing.pipeline import parse_one_version


def test_uppercase_tex_suffix_is_discovered(tmp_path):
    s = tmp_path / '2310-12345' / 'v1' / 'sources'
    s.mkdir(parents=True)
    (s / 'article.TEX').write_text(r'\documentclass{article}\begin{document}Real sentence.\end{document}')
    assert find_document_root(s).name == 'article.TEX'
    parsed = parse_one_version('2310.12345', 1, tmp_path)
    assert not parsed.empty and parsed.n_edges > 0


def test_include_with_period_in_basename(tmp_path):
    s = tmp_path / '2310-12345' / 'v1' / 'sources'
    (s / 'src').mkdir(parents=True)
    (s / 'main.tex').write_text(r'\documentclass{article}\begin{document}\input{src/4.workflow}\end{document}')
    (s / 'src' / '4.workflow.tex').write_text(r'\section{Method} Complex work completed.')
    parsed = parse_one_version('2310.12345', 1, tmp_path)
    assert not parsed.empty and not parsed.partial
    assert parsed.n_edges > 0
    assert any('4.workflow.tex' in x for x in parsed.compilation_files)


def test_twocolumn_fullwidth_title_does_not_swallow_sections(tmp_path):
    s = tmp_path / '2310-12345' / 'v1' / 'sources'
    s.mkdir(parents=True)
    (s / 'main.tex').write_text('''\\documentclass{article}
\\begin{document}
\\twocolumn[{\\begin{center}Title \\\\[5pt] More title\\end{center}}]
\\section{Introduction}
Actual content with several sentences.\\end{document}''')
    parsed = parse_one_version('2310.12345', 1, tmp_path)
    assert not parsed.empty and parsed.n_edges > 0
    assert any(node.content == 'Introduction' for node in parsed.tree.children)
