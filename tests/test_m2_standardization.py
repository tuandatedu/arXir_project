"""End-to-end checks for M2 normalization and cross-version deduplication."""

from __future__ import annotations

import json
from pathlib import Path

from src.m2_parsing.bibitem import collect_version_bibtex, extract_bibitems, parse_bib_file
from src.m2_parsing.cleanup import cleanup_element_content
from src.m2_parsing.dedup import assign_element_ids, dedup_bibtex_across_versions, references_similar, rewrite_citations
from src.m2_parsing.pipeline import _populate_container_content, _prune_empty_nodes, run_milestone2
from src.m2_parsing.hierarchy import ParseNode
from src.m2_parsing.gather import active_tex, concatenate_compilation_tex


def test_cleanup_keeps_semantics_and_unifies_math():
    raw = r"\begin{figure}[htbp]\centering\includegraphics{plot}\midrule\end{figure}"
    cleaned = cleanup_element_content(raw)
    assert "[htbp]" not in cleaned and r"\centering" not in cleaned
    assert r"\includegraphics{plot}" in cleaned
    assert cleanup_element_content(r"A \textbf{nested \emph{word}}.") == "A nested word."
    assert cleanup_element_content(r"Value \(x + 1\) and $$y=2$$") == (
        r"Value $x + 1$ and \begin{equation*}y=2\end{equation*}"
    )


def test_bibtex_balanced_fields_and_bibitem():
    parsed = parse_bib_file('@article{k, title={{A {Nested} Title}}, author={Jane Doe and John Roe}, '
                            'year={2020}, doi={10.1234/test}, journal={Nature}}')
    assert parsed[0]["title"] == "A Nested Title"
    assert parsed[0]["authors"] == ["Jane Doe", "John Roe"]
    assert parsed[0]["doi"] == "10.1234/test"
    items = extract_bibitems(r"\begin{thebibliography}{9}\bibitem{ref} J. Doe. A Study. 2020. doi:10.1234/test.\end{thebibliography}")
    assert len(items) == 1 and items[0]["citation_key"] == "ref"
    commented = "\\begin{thebibliography}{9}\n% \\bibitem{ghost} Ignore this\n\\bibitem{real} J. Doe. A Study.\\end{thebibliography}"
    assert [entry["citation_key"] for entry in extract_bibitems(commented)] == ["real"]


def test_reference_union_and_multi_key_citations():
    rows, aliases = dedup_bibtex_across_versions({
        1: [{"citation_key": "old", "title": "A Study", "authors": ["Jane Doe"], "year": 2020}],
        2: [{"citation_key": "new", "title": "A Study", "authors": ["Jane Doe"], "doi": "10.1234/test"}],
    })
    assert len(rows) == 1 and rows[0].year == 2020 and rows[0].doi == "10.1234/test"
    assert rewrite_citations(r"See \citep[Sec. 2]{new,other}.", aliases) == r"See \citep[Sec. 2]{old,other}."


def test_sparse_same_key_conflicting_years_are_not_merged():
    rows, aliases = dedup_bibtex_across_versions({
        1: [{"citation_key": "ref", "year": 2020}],
        2: [{"citation_key": "ref", "year": 2024}],
    })
    assert len(rows) == 2 and aliases['v1:ref'] != aliases['v2:ref']


def test_bibtex_selects_citations_and_honors_nocite_star(tmp_path):
    (tmp_path / 'refs.bib').write_text('@article{used, title={Used}}\n@article{unused, title={Unused}}', encoding='utf-8')
    tex = r'\bibliography{refs} \parencite[see]{used}'
    assert [x['citation_key'] for x in collect_version_bibtex(tmp_path, tex)] == ['used']
    assert len(collect_version_bibtex(tmp_path, tex + r' \nocite{*}')) == 2
    assert rewrite_citations(r'\parencite[see]{used}', {'used': 'new'}) == r'\parencite[see]{new}'


def test_include_repeats_but_cycles_stop(tmp_path):
    (tmp_path / 'main.tex').write_text(r'\documentclass{article}\input{a}\input{a}', encoding='utf-8')
    (tmp_path / 'a.tex').write_text(r'Repeated.\input{main}', encoding='utf-8')
    assert concatenate_compilation_tex(tmp_path).count('Repeated.') == 2


def test_conditionals_mask_known_inactive_branch_without_guessing_unknown_macro():
    known = active_tex(r'\iffalse Hidden.\else Visible.\fi')
    assert 'Hidden.' not in known and 'Visible.' in known
    unknown = active_tex(r'\ifdefined\packageMacro First.\else Second.\fi')
    assert 'First.' in unknown and 'Second.' in unknown


def test_missing_include_is_partial_and_still_preserves_available_content(tmp_path):
    source = tmp_path / 'working' / '2310-12345' / 'v1' / 'sources'
    source.mkdir(parents=True)
    (source / 'main.tex').write_text(
        r'\documentclass{article}\begin{document}Available text.\input{missing}\end{document}',
        encoding='utf-8')
    elements, _, _ = run_milestone2(tmp_path / 'working', ['2310.12345'], tmp_path / 'tables')
    metrics = json.loads((tmp_path / 'tables' / 'metrics_m2.json').read_text(encoding='utf-8'))
    assert metrics['n_versions_partial'] == 1 and metrics['n_versions_parsed'] == 0
    assert metrics['coverage'][0]['partial_versions'][0]['missing_includes']
    assert any(row.kind == 'sentence' and 'Available text.' in row.content for row in elements)


def test_bibitem_newblock_keeps_title_separate_from_emphasized_journal():
    rows = extract_bibitems(r'\begin{thebibliography}{9}\bibitem{k} Jane Doe. '
                            r'\newblock A Study.\newblock \emph{Journal of Tests}, 2020.\end{thebibliography}')
    assert rows[0]['title'] == 'A Study'
    assert rows[0]['journal'] == 'Journal of Tests'


def test_multiline_math_normalization_preserves_alignment():
    result = cleanup_element_content(r'\begin{align*}x&=1\\ y&=2\end{align*}')
    assert result == r'\begin{equation*}\begin{aligned}x&=1\\ y&=2\end{aligned}\end{equation*}'
    numbered = r'\begin{align}x&=1\\ y&=2\end{align}'
    assert cleanup_element_content(numbered) == numbered


def test_indexed_reference_matching_agrees_with_pairwise_matching():
    entries = [
        {"citation_key": "a", "title": "Same title", "doi": "10.1/a"},
        {"citation_key": "b", "title": "Same title", "doi": "10.1/a"},
        {"citation_key": "c", "title": "Same title"},
        {"citation_key": "d", "title": "Other title", "doi": "10.1/a"},
        {"citation_key": "e", "title": "Unique", "year": 2020},
        {"citation_key": "e", "year": 2020},
        {"citation_key": "f", "title": "Unrelated"},
    ]
    parents = list(range(len(entries)))
    def find(i):
        while parents[i] != i:
            i = parents[i]
        return i
    for i, entry in enumerate(entries):
        for j in range(i):
            if references_similar(entry, entries[j]):
                parents[find(i)] = find(j)
    _, aliases = dedup_bibtex_across_versions({i + 1: [entry] for i, entry in enumerate(entries)})
    for i, first in enumerate(entries):
        for j, second in enumerate(entries):
            assert (aliases[f"v{i + 1}:{first['citation_key']}"] == aliases[f"v{j + 1}:{second['citation_key']}"]) == (find(i) == find(j))


def test_missing_doi_does_not_bridge_distinct_dois():
    rows, aliases = dedup_bibtex_across_versions({
        1: [{'citation_key': 'a', 'title': 'Paper', 'doi': '10.1/a'}],
        2: [{'citation_key': 'b', 'title': 'Paper', 'doi': '10.1/b'}],
        3: [{'citation_key': 'c', 'title': 'Paper'}],
    })
    assert len(rows) == 2
    assert aliases['v1:a'] != aliases['v2:b']


def test_cleanup_drops_empty_sentence_and_parent_paragraph():
    root = ParseNode("document", "", [ParseNode("paragraph", "", [ParseNode("sentence", r"\centering")])])
    _prune_empty_nodes(root)
    assert root.children == []


def test_paragraph_content_reflects_its_sentences():
    root = ParseNode("document", "", [
        ParseNode("paragraph", "", [ParseNode("sentence", "First sentence.")]),
        ParseNode("paragraph", "", [ParseNode("sentence", "Second sentence.")]),
    ])
    _populate_container_content(root)
    assert [child.content for child in root.children] == ["First sentence.", "Second sentence."]


def test_repeated_text_reuses_id_across_and_within_versions():
    def tree():
        return ParseNode("document", "", [
            ParseNode("paragraph", "", [ParseNode("sentence", "Repeated.")]),
            ParseNode("paragraph", "", [ParseNode("sentence", "Repeated.")]),
        ])
    trees = {1: tree(), 2: tree()}
    for root in trees.values():
        _populate_container_content(root)
    elements, edges = assign_element_ids("2310.12345", trees)
    sentences = [row for row in elements if row.kind == "sentence"]
    assert len(sentences) == 1
    assert all({edge.version for edge in edges if edge.element_id == row.element_id} == {1, 2}
               for row in sentences)


def test_reference_read_failure_is_not_counted_as_parsed(tmp_path: Path, monkeypatch):
    source = tmp_path / "working" / "2310-12345" / "v1" / "sources"
    source.mkdir(parents=True)
    (source / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Hello.\end{document}", encoding="utf-8"
    )

    def fail_read(*_args):
        raise OSError("bibliography unavailable")

    monkeypatch.setattr("src.m2_parsing.pipeline.collect_version_bibtex", fail_read)
    run_milestone2(tmp_path / "working", ["2310.12345"], tmp_path / "tables")
    metrics = json.loads((tmp_path / "tables" / "metrics_m2.json").read_text(encoding="utf-8"))
    assert (metrics["n_versions_total"], metrics["n_versions_parsed"], metrics["n_versions_failed"]) == (1, 0, 1)
    assert metrics["coverage"][0]["parsed_versions"] == []


def test_missing_source_is_failure_not_empty_record(tmp_path: Path):
    version = tmp_path / 'working' / '2310-12345' / 'v1'
    version.mkdir(parents=True)
    run_milestone2(tmp_path / 'working', ['2310.12345'], tmp_path / 'tables')
    metrics = json.loads((tmp_path / 'tables' / 'metrics_m2.json').read_text(encoding='utf-8'))
    assert (metrics['n_versions_empty'], metrics['n_versions_failed']) == (0, 1)
    assert metrics['coverage'][0]['failed_versions'][0]['error'] == 'missing sources directory'


def test_full_pipeline_two_versions_and_empty(tmp_path: Path):
    working = tmp_path / "working"
    publication = working / "2310-12345"
    (publication / "paper.json").parent.mkdir(parents=True)
    (publication / "paper.json").write_text(json.dumps({"arxiv_id": "2310.12345"}))
    v1 = publication / "v1" / "sources"
    v2 = publication / "v2" / "sources"
    v1.mkdir(parents=True)
    v2.mkdir(parents=True)
    (publication / "v3" / "empty.json").parent.mkdir()
    (publication / "v3" / "empty.json").write_text("{}")
    (v1 / "main.tex").write_text(r"""\documentclass{article}
\begin{document}
\section{Intro}
Same sentence with \cite{old}.
\begin{thebibliography}{9}
\bibitem{old} Jane Doe. A Study. 2020.
\end{thebibliography}
\end{document}""")
    (v2 / "main.tex").write_text(r"""\documentclass{article}
\begin{document}
\section{Intro}
Same sentence with \cite{new}.
\bibliography{refs}
\end{document}""")
    (v2 / "refs.bib").write_text('@article{new, title={A Study}, author={Jane Doe}, year={2020}, doi={10.1234/test}}')
    elements, hierarchy, bibtex = run_milestone2(working, tables_dir=tmp_path / "tables")
    assert len(bibtex) == 1
    assert bibtex[0].doi == "10.1234/test"
    assert bibtex[0].citation_key == "old"
    sentences = [row for row in elements if row.kind == "sentence" and "Same sentence" in row.content]
    assert len(sentences) == 1 and r"\cite{old}" in sentences[0].content
    assert {row.version for row in hierarchy if row.element_id == sentences[0].element_id} == {1, 2}
    assert not any(row.version == 3 for row in hierarchy)
    metrics = json.loads((tmp_path / "tables" / "metrics_m2.json").read_text())
    assert metrics["n_versions_empty"] == 1
    assert metrics["n_elements_before_dedup"] > metrics["n_elements_after_dedup"]
    assert metrics["n_bib_before"] == 2 and metrics["n_bib_after"] == 1
