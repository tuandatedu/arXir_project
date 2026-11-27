import json
import pytest
from src.m2_parsing.bibitem import extract_bibitems, collect_version_bibtex, parse_bib_file, citation_keys
from src.m2_parsing.cleanup import cleanup_element_content
from src.m2_parsing.dedup import dedup_bibtex_across_versions
from src.m2_parsing.pipeline import run_milestone2

def wrap(body):
    return r'\begin{thebibliography}{9}' + body + r'\end{thebibliography}'

@pytest.mark.parametrize('locator,year', [('2031 (1970)',1970),('1979 (1984)',1984),('2025 (2012)',2012)])
def test_page_is_not_publication_year(locator, year):
    row = extract_bibitems(wrap(r'\bibitem{k} S. H. Groves, J. Phys. Chem. Solids 31, '+locator+'.'))[0]
    assert row['year'] == year
    assert row['title'] is None

def test_year_in_title_and_doi_is_not_year():
    row = extract_bibitems(wrap(r'\bibitem{k} J. Doe. Records spanning 2000 years. Journal 31 (2006). doi:10.1234/2024.'))[0]
    assert row['year'] == 2006

def test_whitespace_optional_natbib_label_and_structured_fields():
    raw = r'\bibitem [{\citenamefont{Doe}(2020)}]{key} \bibfield {author} {\bibinfo {author} {\bibfnamefont{J.}~\bibnamefont{Doe}}} \bibfield{title}{\bibinfo{title}{{A useful title}}} \bibinfo{journal}{Journal of Tests} (\bibinfo{year}{2020}).'
    row = extract_bibitems(wrap(raw))[0]
    assert row['citation_key'] == 'key'
    assert row['title'] == 'A useful title'
    assert row['authors'] == ['J. Doe']
    assert row['year'] == 2020

def test_emphasized_title_does_not_leak_into_author():
    row = extract_bibitems(wrap(r'\bibitem{k} A. A. Dorogovtsev \emph{Visiting measures and an ergodic theorem}, Ukr Math J \textbf{51}, (1999), 134--139.'))[0]
    assert row['authors'] == ['A. A. Dorogovtsev']
    assert row['title'] == 'Visiting measures and an ergodic theorem'

def test_bbl_only_and_addbibresource_options(tmp_path):
    (tmp_path/'main.bbl').write_text(wrap(r'\bibitem{x} J. Doe. A Study. 2020.'), encoding='utf8')
    assert collect_version_bibtex(tmp_path,r'\cite{x}\bibliography{missing}')[0]['citation_key']=='x'
    (tmp_path/'refs.bib').write_text('@article{x,title={Structured title},year={2020}}',encoding='utf8')
    rows=collect_version_bibtex(tmp_path,r'\cite{x}\addbibresource[location=local]{refs.bib}')
    assert len(rows)==1 and rows[0]['title']=='Structured title'
    assert collect_version_bibtex(tmp_path,r'No citations here.')==[]

def test_bibtex_string_concat_corporate_author_and_historical_year():
    rows=parse_bib_file('@string{j="Journal of Tests"}\n@article{x,title="One " # "title",journal=j,author={{Research and Development Team} and Jane Doe},year={1899}}')
    assert rows[0]['title']=='One title'
    assert rows[0]['journal']=='Journal of Tests'
    assert rows[0]['authors']==['Research and Development Team','Jane Doe']
    assert rows[0]['year']==1899

def test_undefined_journal_string_keeps_other_fields_and_flags_review():
    row=parse_bib_file('@article{x,title={Known title},author={Jane Doe},journal=undefinedjournal,year={2020}}')[0]
    assert row['title']=='Known title' and row['authors']==['Jane Doe'] and row['year']==2020
    assert row['journal'] is None
    assert row['_parse_warnings']==['undefined_bibtex_string:journal']

@pytest.mark.parametrize('raw,expected', [
    (r'Value $\ensuremath{x}$.',r'Value $\ensuremath{x}$.'),
    (r'Value \ensuremath{x_{i}}.',r'Value $x_{i}$.'),
    (r'$a\mbox{ if }b$',r'$a\mbox{ if }b$'),
    (r'$\textbf{x}+y$',r'$\textbf{x}+y$'),
    (r'$x$$y$',r'$x$$y$'),
    (r'\begin{tabular}{c}a\\[5pt]b\end{tabular}',r'\begin{tabular}{c}a\\[5pt]b\end{tabular}'),
    (r'\verb|a  b|',r'\verb|a  b|'),
    (r'\begin{aligned}\textbf{x}&=1\end{aligned}',r'\begin{aligned}\textbf{x}&=1\end{aligned}'),
])
def test_math_and_literal_context_and_idempotency(raw,expected):
    cleaned=cleanup_element_content(raw)
    assert cleaned==expected
    assert cleanup_element_content(cleaned)==cleaned

def test_doi_punctuation_and_unicode_titles_do_not_collide():
    rows,_=dedup_bibtex_across_versions({1:[{'citation_key':'a','doi':'10.1234/a-b','title':'First'}],2:[{'citation_key':'b','doi':'10.1234/ab','title':'Other'}]})
    assert len(rows)==2
    rows,_=dedup_bibtex_across_versions({1:[{'citation_key':'a','title':'数学','year':2020}],2:[{'citation_key':'b','title':'物理','year':2020}]})
    assert len(rows)==2

def test_audit_ignores_wildcards_placeholders_and_literals():
    assert citation_keys(r'\nocite{*}\cite{#1,real}\verb|\cite{fake}|')=={'real'}

def test_publication_resume_rechecks_source_and_output_hashes(tmp_path, monkeypatch):
    from src.m2_parsing import pipeline
    source=tmp_path/'working'/'2310-12345'/'v1'/'sources'
    source.mkdir(parents=True)
    main=source/'main.tex'
    main.write_text(r'\documentclass{article}\begin{document}Original sentence.\end{document}',encoding='utf8')
    out=tmp_path/'tables';working=tmp_path/'working'
    run_milestone2(working,['2310.12345'],out)
    original=pipeline.parse_one_version
    def must_not_parse(*a,**kw): raise AssertionError('Should reuse the verified publication')
    monkeypatch.setattr(pipeline,'parse_one_version',must_not_parse)
    run_milestone2(working,['2310.12345'],out)
    assert json.loads((out/'metrics_m2.json').read_text())['n_publications_reused']==1
    monkeypatch.setattr(pipeline,'parse_one_version',original)
    main.write_text(main.read_text().replace('Original','Modified'),encoding='utf8')
    rows,_,_=run_milestone2(working,['2310.12345'],out)
    assert any('Modified' in r.content for r in rows)
    parsed=source.parents[1]/'parsed'/'elements.jsonl'
    parsed.write_text(parsed.read_text().replace('Modified','Tampered'),encoding='utf8')
    rows,_,_=run_milestone2(working,['2310.12345'],out)
    assert all('Tampered' not in r.content for r in rows)

def test_selected_bibliography_keeps_later_strings_and_skips_unused(tmp_path):
    (tmp_path/'refs.bib').write_text('@article{used,title={Used},journal=j}\n@article{unused,title={Not cited}}\n@string{j="Known journal"}',encoding='utf8')
    rows=collect_version_bibtex(tmp_path,r'\cite{used}\bibliography{refs}')
    assert len(rows)==1 and rows[0]['journal']=='Known journal'

def test_relative_working_path_root_coverage_warning_does_not_crash(tmp_path,monkeypatch):
    from src.m2_parsing.pipeline import parse_one_version
    s=tmp_path/'working'/'2310-12345'/'v1'/'sources';s.mkdir(parents=True)
    (s/'main.tex').write_text(r'\documentclass{article}\begin{document}Short body.\end{document}',encoding='utf8')
    for i in range(4):(s/f'unused{i}.tex').write_text('Unused body text. '*100,encoding='utf8')
    monkeypatch.chdir(tmp_path)
    result=parse_one_version('2310.12345',1,__import__('pathlib').Path('working'))
    assert not result.empty and result.root_coverage_review
