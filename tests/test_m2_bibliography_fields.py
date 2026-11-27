"""Source-backed bibliography regressions, including the 485 reviewed references."""
from pathlib import Path
import csv
import pytest
from src.m2_parsing.bibliography_fields import parse_explicit_bibitem, split_explicit_names, norm
from src.m2_parsing.bibitem import extract_bibitems

RESOURCE = Path(__file__).parent / "fixtures" / "m2"

def wrap(text):return r'\begin{thebibliography}{9}'+text+r'\end{thebibliography}'

@pytest.mark.parametrize('name,expected',[
    ('Srikanth B. Iyengar and Ryo Takahashi',['Srikanth B. Iyengar','Ryo Takahashi']),
    ('Özgür Esentepe',['Özgür Esentepe']),
    ('Alex S. Dugas, Graham J. Leuschke',['Alex S. Dugas','Graham J. Leuschke']),
    ('Dugas, Alex S., Leuschke, Graham J.',['Dugas, Alex S.','Leuschke, Graham J.']),
    ('Aubin, J.-P.; Da Prato, G.',['Aubin, J.-P.','Da Prato, G.']),
    ('Răşcanu, A.; Rotenstein, E., The',['Răşcanu, A.','Rotenstein, E.']),
])
def test_explicit_names_preserve_accents_initials_and_comma_forms(name,expected):
    assert split_explicit_names(name)==expected

def test_all_485_source_evidence_rows_recover_authors():
    with (RESOURCE/'bibliography_source_cases.csv').open(encoding='utf-8-sig',newline='') as source:rows=list(csv.DictReader(source))
    assert len(rows)==485
    assert len({row['arxiv_id'] for row in rows})==143
    for row in rows:
        result=extract_bibitems(wrap(r'\bibitem{k} '+row['raw_excerpt']))[0]
        expected=split_explicit_names(row['authors_in_source'])
        assert expected and {norm(n) for n in expected}<={norm(n) for n in result['authors']},row['citation_key']
        if 'ISBN_USED_AS_TITLE' in row['reasons']:
            assert norm(result['title'])==norm(row['emphasized_source_text'])

def test_styled_journal_does_not_fabricate_missing_article_title():
    row=extract_bibitems(wrap(r'\bibitem{k} Jane Doe, \emph{Phys. Rev. B}, 31, 2031 (1970).'))[0]
    assert row['authors']==['Jane Doe'] and row['title'] is None
    assert row['year']==1970
    assert parse_explicit_bibitem(r'Jane Doe. A Plain Title. \emph{Journal}, 2020.') is None

def test_styled_title_includes_adjacent_inline_math_and_more_styled_text():
    row=extract_bibitems(wrap(r'\bibitem{k} Jane Doe, \textit{A result in }$\mathbb{R}^{d}$\textit{ with noise}, Journal 31 (2020).'))[0]
    assert row['title']==r'A result in $\mathbb{R}^{d}$ with noise'
