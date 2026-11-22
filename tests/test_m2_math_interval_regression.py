"""Regression: math interval tokens must never eat subsequent scientific sections."""
from src.m2_parsing.hierarchy import parse_tex_to_tree, flatten_tree
from src.m2_parsing.gather import active_tex


def titles(tex):
    t = parse_tex_to_tree(r'\documentclass{article}\begin{document}' + tex + r'\end{document}')
    return [n.content for n, _ in flatten_tree(t)
            if n.kind in ('heading','appendix','acknowledgement')]


def test_half_open_math_interval_followed_by_appendix():
    tex = r'\section{Intro} A variable $u\in[0,1)$ is sampled.' + '\n' + r'\appendix\section{Dataset Construction}\subsection{Sampling} Details.'
    assert titles(tex) == ['Intro', 'Dataset Construction', 'Sampling']


def test_to_half_open_interval_followed_by_conclusion():
    tex = r'\section{Method} We map $f\to[0,\infty)$.' + '\n' + r'\section{Conclusion} All done.'
    assert titles(tex) == ['Method', 'Conclusion']


def test_math_approx_and_subset_operators_with_square_brackets():
    tex = r'\section{First} $f\approx[0,2\pi)$ and $A\subseteq[0,1]$.'+'\n'+r'\section{Second} Keep this.'
    assert titles(tex) == ['First','Second']


def test_math_parentheses_interval_followed_by_heading():
    tex = r'\section{First} Let \(x\in[0,1)\) be chosen.' + '\n' + r'\section{Second} Exists.'
    assert titles(tex) == ['First', 'Second']


def test_actual_option_argument_not_lost():
    tex = r'\section{Intro} \textcolor[HTML]{FFFFFF}{White} text.' + '\n' + r'\section{Conclusion} Done.'
    assert titles(tex) == ['Intro', 'Conclusion']


def test_unclosed_optional_lookahead_does_not_consume_following_sections():
    tex = r'\section{Intro} An incomplete \custom[alpha is visible.'+'\n'+r'\section{Conclusion} Keep this.'
    assert titles(tex) == ['Intro','Conclusion']


def test_heading_audit_finds_silently_missing_section():
    from src.m2_parsing.hierarchy import audit_source_headings, ParseNode
    tex = (r'\documentclass{article}\begin{document}'
           r'\section{Intro} Text. \section{Lost Appendix} Details.'
           r'\end{document}')
    n, missing = audit_source_headings(tex, ParseNode(kind='document', content=''))
    assert n == 2
    assert missing == ['Intro', 'Lost Appendix']


def test_heading_audit_recognizes_appendix_and_excludes_references():
    from src.m2_parsing.hierarchy import audit_source_headings
    tex = (r'\documentclass{article}\begin{document}'
           r'\section{Intro} Text. \appendix\section{Appendix Experiments} More.'
           r'\section{References} \begin{thebibliography}{9} \end{thebibliography}'
           r'\end{document}')
    n, missing = audit_source_headings(tex, parse_tex_to_tree_for_test(tex))
    assert n == 2
    assert missing == []


def parse_tex_to_tree_for_test(tex):
    from src.m2_parsing.hierarchy import parse_tex_to_tree
    return parse_tex_to_tree(tex)
