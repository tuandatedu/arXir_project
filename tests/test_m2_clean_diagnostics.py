"""Evidence-based classification protects against known M2 false positives."""
import json
from pathlib import Path
from src.m2_parsing.diagnostics import classify_coverage, save_diagnostics
from src.m2_parsing.hierarchy import _m2_clean_unwrap, parse_tex_to_tree


def _paper(pid, status, trace):
    result = {'arxiv_id':pid,'versions':[1],'source_trace':[dict(version=1,**trace)],
              'parsed_versions':[],'empty_versions':[],'partial_versions':[],
              'failed_versions':[]}
    result[status].append(1 if status in ('parsed_versions','empty_versions') else {'version':1,'error':'problem'})
    return result


def test_no_latex_skip_and_not_parser_error(tmp_path):
    metrics={'n_versions_total':1,'n_publications':1,'coverage':[
        _paper('2310.12345','empty_versions',{'reason':'missing sources directory'})]}
    rows=classify_coverage(metrics)
    assert rows[0]['status']=='SKIP_NO_LATEX'
    assert save_diagnostics(metrics,tmp_path)['status_counts']['SKIP_NO_LATEX']==1
    assert '2310.12345' in (tmp_path/'paper_status.jsonl').read_text()


def test_placeholder_and_template_no_false_parser_errors():
    metrics={'n_versions_total':1,'n_publications':1,'coverage':[
        _paper('2310.12345','parsed_versions',{
            'root_file':'Template.tex','source_characters':12000,
            'unrepresented_headings':['#1'],'missing_includes':[]})]}
    rows=classify_coverage(metrics)
    assert rows[0]['status']=='PARSED'
    assert any(x['type']=='INFO_PLACEHOLDER_HEADING' for x in rows[0]['details'])


def test_known_support_include_not_real_missing_content():
    metrics={'n_versions_total':1,'n_publications':1,'coverage':[
        _paper('2310.12345','partial_versions',{
            'root_file':'main.tex','reason':'unresolved TeX includes',
            'source_characters':20000,'missing_includes':['main.tex: xy']})]}
    assert classify_coverage(metrics)[0]['status']=='PARSED_WITH_SUPPORT_INCLUDE_WARNING'


def test_heading_mismatch_is_review_not_confirmed_error():
    metrics={'n_versions_total':1,'n_publications':1,'coverage':[
        _paper('2310.12345','parsed_versions',{
            'root_file':'main.tex','source_characters':20000,
            'unrepresented_headings':['Numerical Experiments']})]}
    row=classify_coverage(metrics)[0]
    assert row['status']=='PARSED_NEEDS_REVIEW'
    assert row['unrepresented_headings']==['Numerical Experiments']


def test_wrappers_and_macro_placeholders_regression():
    samples=[
        (r'\begin{document}\hypertarget{id}{\section{Method}}\end{document}',r'\section{Method}'),
        (r'\begin{document}\textcolor{blue}{\subsection{Results}}\end{document}',r'\subsection{Results}'),
        (r'\begin{document}\newtext{\subsubsection{Discussion}}\end{document}',r'\subsubsection{Discussion}'),
        (r'\begin{document}\colorbox{yellow}{\section{Notes}}\end{document}',r'\section{Notes}'),
        (r'\begin{document}\mbox{\paragraph{Details}}\end{document}',r'\paragraph{Details}'),
    ]
    for tex,wanted in samples:
        assert wanted in _m2_clean_unwrap(tex)
        parse_tex_to_tree(tex)
    tex=r'\begin{document}\newtext{\section{#1}}\end{document}'
    assert _m2_clean_unwrap(tex)==tex


def test_input_paper_without_any_version_gets_explicit_skip(tmp_path):
    metrics={'n_versions_total':0,'n_publications':1,'coverage':[
        {'arxiv_id':'2310.12345','versions':[],'source_trace':[],
         'parsed_versions':[],'empty_versions':[], 'failed_versions':[],
         'partial_versions':[]}]}
    summary=save_diagnostics(metrics,tmp_path)
    assert summary['status_counts']['SKIP_NO_M1_RECORD']==1
    assert summary['n_input_missing_publication_records']==1
