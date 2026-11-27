"""Targeted regression suite for actual source failures and adversarial TeX."""
import json
from pathlib import Path

import pytest

from src.m2_parsing.hierarchy import (parse_tex_to_tree, flatten_tree,
                                       audit_source_headings)
from src.m2_parsing.bibitem import parse_bib_file, extract_bibitems
from src.m2_parsing.quality_checks import validate_range_output
from src.m2_parsing.batch_pipeline import PIPELINE_REVISION


def headings(tex):
    tree = parse_tex_to_tree(r'\documentclass{article}\begin{document}' + tex + r'\end{document}')
    return [node.content for node, _ in flatten_tree(tree)
            if node.kind in ('heading', 'appendix', 'acknowledgement')]


def test_heading_can_have_newline_between_command_and_argument():
    tex = '\\section\n{Introduction} Starting.\\subsection*\n[Short]\n{Approach} Detail.'
    assert headings(tex) == ['Introduction', 'Approach']


def test_malformed_heading_option_does_not_eat_later_section():
    tex = r'\section[unclosed choice ' + '\n' + r'\section{Conclusion} Important result.'
    assert 'Conclusion' in headings(tex)


def test_nested_command_in_heading_is_visible_to_source_audit():
    tex = r'\documentclass{article}\begin{document}\section{\textbf{Nested} Title} Content.\end{document}'
    tree = parse_tex_to_tree(tex)
    count, missing = audit_source_headings(tex, tree)
    assert count == 1 and missing == []


def test_duplicate_heading_source_count_not_masked_by_set():
    tex = r'\documentclass{article}\begin{document}\section{Repeated}\section{Repeated}\end{document}'
    tree = parse_tex_to_tree(r'\documentclass{article}\begin{document}\section{Repeated}\end{document}')
    count, missing = audit_source_headings(tex, tree)
    assert count == 2 and missing == ['Repeated']


def test_unicode_heading_not_reduced_to_empty_audit_key():
    tex = r'\documentclass{article}\begin{document}\section{Giới thiệu}\end{document}'
    from src.m2_parsing.hierarchy import ParseNode
    _, missing = audit_source_headings(tex, ParseNode('document', ''))
    assert missing == ['Giới thiệu']


def test_literal_math_environment_preserves_math_marker():
    tex = r'\section{Theory} We use \begin{math}x^{2}+1\end{math} here. '
    tree = parse_tex_to_tree(r'\documentclass{article}\begin{document}' + tex + r'\end{document}')
    sentences = [n.content for n, _ in flatten_tree(tree) if n.kind == 'sentence']
    assert any('$x^{2}+1$' in s for s in sentences)


def test_fbox_minipage_heading_is_not_swallowed():
    tex = r'\section{Method}\fbox{\begin{minipage}{0.9\linewidth}\paragraph{Bandwise hybridization form.} Detailed scientific content.\end{minipage}}'
    assert headings(tex) == ['Method', 'Bandwise hybridization form.']


@pytest.mark.parametrize('prefix', ['$$', r'\['])
def test_unmatched_display_delimiter_never_swallow_conclusion(prefix):
    tex = r'\section{Methods} Text. ' + prefix + ' partial math. ' + r'\section{Conclusion} Retained.'
    assert headings(tex) == ['Methods', 'Conclusion']


def test_unclosed_macro_brace_does_not_swallow_heading():
    tex = r'\section{Methods} Text. \custom{broken bracing ' + '\n' + r'\section{Conclusion} Retained.'
    assert headings(tex) == ['Methods', 'Conclusion']


def test_ghost_bibtex_entry_within_comment_not_emitted():
    raw = r'@comment{One sample: @article{ghost, title={Not real}}}' + '\n' + r'@article{real, title={Real paper}, year={2020}}'
    parsed = parse_bib_file(raw)
    assert [r['citation_key'] for r in parsed] == ['real']


def test_bibitem_in_verbatim_code_is_not_real():
    src = (r'\begin{verbatim}\begin{thebibliography}{9}\bibitem{ghost} Fake.\end{thebibliography}\end{verbatim}'
           + r'\begin{thebibliography}{9}\bibitem{real} Real author. Real title.\end{thebibliography}')
    assert [x['citation_key'] for x in extract_bibitems(src)] == ['real']


def test_semantic_review_is_explicit_and_complete(tmp_path):
    folder = tmp_path/'table'
    folder.mkdir()
    p='2301.12345'
    m={'pipeline_revision':PIPELINE_REVISION,'n_publications':1,'n_versions_total':1,
       'n_versions_parsed':1,'n_versions_empty':0,'n_versions_failed':0,
       'n_versions_partial':0,'n_elements_after_dedup':2,'n_bib_after':0,
       'n_hierarchy_edges':1,'coverage':[{
           'arxiv_id':p,'versions':[1],'n_versions':1,'parsed_versions':[1],
           'empty_versions':[],'failed_versions':[],'partial_versions':[],
           'n_parsed':1,'n_empty':0,'n_failed':0,'n_partial':0,
           'n_elements_after_dedup':2,'n_bib_after':0,'source_trace':[{
               'version':1,'root_file':'template.tex','source_characters':12345,
               'unrepresented_headings':['Conclusion'],'missing_includes':[]}]}]}
    (folder/'metrics_m2.json').write_text(json.dumps(m))
    (folder/'elements.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in [
        {'arxiv_id':p,'element_id':'doc1','kind':'document','content':'Article'},
        {'arxiv_id':p,'element_id':'node1','kind':'heading','content':'Introduction'}]))
    (folder/'hierarchy.jsonl').write_text(json.dumps({'arxiv_id':p,'version':1,'element_id':'node1','parent_id':'doc1'})+'\n')
    (folder/'bibtex.jsonl').write_text('')
    qa=validate_range_output(folder)
    assert qa['passed'] is True
    assert qa['needs_content_review'] is True
    assert qa['hierarchy_foreign_keys_checked'] == 1
    assert qa['source_heading_review_count'] == 1
    reviews=[json.loads(line) for line in (folder/'semantic_review.jsonl').read_text().splitlines()]
    assert reviews[0]['unrepresented_headings'] == ['Conclusion']
    # A syntactically plausible but orphaned edge must never be QA-PASS.
    (folder/'hierarchy.jsonl').write_text(json.dumps({'arxiv_id':p,'version':1,'element_id':'MISSING','parent_id':'doc1'})+'\n')
    with pytest.raises(ValueError,match='foreign key'):
        validate_range_output(folder)
