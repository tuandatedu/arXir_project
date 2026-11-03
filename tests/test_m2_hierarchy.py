"""Tests for M2 compilation-path gathering and pre-normalization trees."""
from __future__ import annotations

from pathlib import Path

from src.common.io import write_json
from src.m2_parsing.gather import (
    compilation_path,
    concatenate_compilation_tex,
    extract_include_targets,
    find_document_root,
    strip_tex_line_comments,
    unused_tex_files,
)
from src.m2_parsing.hierarchy import (
    heading_level,
    is_acknowledgement_or_appendix,
    is_references_heading,
    nodes_and_edges,
    parse_tex_to_tree,
    split_sentences,
)
from src.m2_parsing.pipeline import parse_one_version, run_raw_hierarchy


def _kinds(node) -> list[str]:
    out = [node.kind]
    for child in node.children:
        out.extend(_kinds(child))
    return out


def _texts(node, kind: str) -> list[str]:
    found = []
    if node.kind == kind:
        found.append(node.content)
    for child in node.children:
        found.extend(_texts(child, kind))
    return found


def test_strip_comments_keeps_escaped_percent():
    text = "100\\% done % comment\nreal"
    assert strip_tex_line_comments(text) == "100\\% done \nreal"


def test_commented_include_is_ignored():
    tex = "% \\input{secret}\n\\input{real}\n\\include{ch2}\n\\includegraphics{fig.png}\n"
    assert extract_include_targets(tex) == ["real", "ch2"]


def test_find_root_and_unused_files(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "unused.tex").write_text("\\section{Ghost} skip me.", encoding="utf-8")
    (sources / "intro.tex").write_text("\\section{Intro} Hello world.\n", encoding="utf-8")
    (sources / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Before.\n"
        "\\input{intro}\n"
        "% \\input{unused}\n"
        "After.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (sources / "sub").mkdir()
    (sources / "sub" / "also_unused.tex").write_text("nope", encoding="utf-8")

    root = find_document_root(sources)
    assert root is not None and root.name == "main.tex"
    used = [p.name for p in compilation_path(sources)]
    assert used == ["main.tex", "intro.tex"]
    unused = {p.name for p in unused_tex_files(sources)}
    assert unused == {"unused.tex", "also_unused.tex"}
    merged = concatenate_compilation_tex(sources)
    assert "Hello world" in merged
    assert "Ghost" not in strip_tex_line_comments(merged)
    assert "Before." in merged and "After." in merged


def test_multiple_documentclass_prefers_main(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "frag.tex").write_text(
        "\\documentclass{article}\\begin{document}frag\\end{document}", encoding="utf-8"
    )
    (sources / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\input{frag}\\end{document}",
        encoding="utf-8",
    )
    assert find_document_root(sources).name == "main.tex"


def test_heading_helpers():
    assert heading_level("\\section*") == 3
    assert heading_level("subsection") == 4
    assert heading_level("textbf") is None
    assert is_references_heading("References")
    assert is_references_heading("Bibliography")
    assert not is_references_heading("Related Work")
    assert is_acknowledgement_or_appendix("Acknowledgements", "section") == "acknowledgement"
    assert is_acknowledgement_or_appendix("Appendix A", "section") == "appendix"


def test_split_sentences_protects_abbreviation_url_math_decimal():
    text = (
        "We use i.e. dropout and e.g. Adam, see Fig. 1 and et al. 2017. "
        "The rate is 3.14 at https://example.com/a.b/c. "
        "Then $a.b + c$ holds. Next sentence."
    )
    sentences = split_sentences(text)
    assert any("i.e." in s and "Fig. 1" in s and "et al." in s for s in sentences)
    assert any("3.14" in s and "https://example.com/a.b/c" in s for s in sentences)
    assert any("$a.b + c$" in s for s in sentences)
    assert sentences[-1] == "Next sentence."


def test_parse_structure_lists_math_figure_table_ack_appendix():
    tex = r"""
\documentclass{article}
\title{Toy Paper}
\begin{document}
\section{Introduction}
We study parsing. It works well.

\begin{equation}
E = mc^2
\end{equation}

\begin{figure}[ht]
\centering
\includegraphics{a.png}
\caption{A figure.}
\end{figure}

\begin{table}
\begin{tabular}{cc}
1 & 2 \\
\end{tabular}
\caption{A table.}
\end{table}

\begin{itemize}
\item First point. Second clause.
\item Nested math $$x+y$$ here.
\end{itemize}

\section*{Acknowledgements}
We thank colleagues.

\section{References}
\cite{x} should vanish.

\section*{Appendix}
Extra proof.
\end{document}
"""
    tree = parse_tex_to_tree(tex)
    assert tree.kind == "document"
    assert tree.content == "Toy Paper"
    kinds = _kinds(tree)
    assert "heading" in kinds
    assert "formula" in kinds
    assert "figure" in kinds
    assert "list" in kinds
    assert "list_item" in kinds
    assert "acknowledgement" in kinds
    assert "appendix" in kinds
    assert "sentence" in kinds
    joined = " ".join(_texts(tree, "sentence"))
    assert "should vanish" not in joined
    assert "We thank colleagues" in joined
    assert "Extra proof" in joined
    figures = _texts(tree, "figure")
    assert len(figures) == 2
    assert any("tabular" in fig for fig in figures)
    formulas = _texts(tree, "formula")
    assert any("E = mc^2" in f for f in formulas)


def test_empty_tex_still_has_document_root():
    tree = parse_tex_to_tree("")
    assert tree.kind == "document"
    assert tree.children == []
    nodes, edges = nodes_and_edges(tree, version=1)
    assert len(nodes) == 1
    assert edges == []


def test_ieee_and_chapter_styles():
    ieee = r"""
\documentclass{IEEEtran}
\begin{document}
\section{Background}
Signal processing is used.
\subsection{Model}
Details follow.
\end{document}
"""
    tree = parse_tex_to_tree(ieee)
    headings = _texts(tree, "heading")
    assert headings == ["Background", "Model"]
    # subsection nests under section
    intro = tree.children[0]
    assert intro.content == "Background"
    assert any(child.content == "Model" for child in intro.children)

    memoir = r"""
\documentclass{memoir}
\begin{document}
\chapter{One}
Alpha.
\section{Inside}
Beta.
\end{document}
"""
    tree2 = parse_tex_to_tree(memoir)
    assert _texts(tree2, "heading") == ["One", "Inside"]
    assert tree2.children[0].content == "One"
    assert tree2.children[0].children[0].kind in {"paragraph", "heading"}


def test_parse_one_version_pipeline(tmp_path: Path):
    pub = tmp_path / "2310-12345"
    v1 = pub / "v1" / "sources"
    v1.mkdir(parents=True)
    (pub / "paper.json").write_text(
        '{"arxiv_id": "2310.12345", "title": "T"}', encoding="utf-8"
    )
    (v1 / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\section{A} Hello.\\end{document}",
        encoding="utf-8",
    )
    v2 = pub / "v2"
    v2.mkdir()
    write_json(v2 / "empty.json", {"empty": True, "reason": "pdf"})

    result = parse_one_version("2310.12345", 1, working_dir=tmp_path)
    assert not result.empty
    assert result.n_edges >= 1
    empty = parse_one_version("2310.12345", 2, working_dir=tmp_path)
    assert empty.empty
    assert empty.tree.kind == "document"

    summaries = run_raw_hierarchy(working_dir=tmp_path, arxiv_ids=["2310.12345"])
    assert summaries[0]["n_parsed"] == 1
    assert summaries[0]["n_empty"] == 1
    assert (pub / "parsed" / "raw" / "v1" / "tree.json").exists()
    assert (pub / "parsed" / "raw" / "v1" / "edges.jsonl").exists()


def test_two_versions_different_trees(tmp_path: Path):
    pub = tmp_path / "2310-99999"
    pub.mkdir(parents=True)
    (pub / "paper.json").write_text('{"arxiv_id":"2310.99999"}', encoding="utf-8")
    for version, section in ((1, "Introduction"), (2, "Background and model")):
        sources = pub / f"v{version}" / "sources"
        sources.mkdir(parents=True)
        (sources / "main.tex").write_text(
            "\\documentclass{article}\\begin{document}"
            f"\\section{{{section}}} We study the citation matching problem."
            "\\end{document}",
            encoding="utf-8",
        )
    r1 = parse_one_version("2310.99999", 1, working_dir=tmp_path)
    r2 = parse_one_version("2310.99999", 2, working_dir=tmp_path)
    assert _texts(r1.tree, "heading") == ["Introduction"]
    assert _texts(r2.tree, "heading") == ["Background and model"]
    s1 = _texts(r1.tree, "sentence")
    s2 = _texts(r2.tree, "sentence")
    assert s1 == s2


def test_unbraced_and_nested_includes(tmp_path: Path):
    sources = tmp_path / "sources"
    (sources / "chapters").mkdir(parents=True)
    (sources / "chapters" / "methods.tex").write_text(
        "\\subsection{Method} Nested file is compiled.\n", encoding="utf-8"
    )
    (sources / "body.tex").write_text(
        "\\section{Body}\\input{chapters/methods}\n", encoding="utf-8"
    )
    (sources / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\input body\\end{document}\n",
        encoding="utf-8",
    )
    used = [p.relative_to(sources).as_posix() for p in compilation_path(sources)]
    assert used == ["main.tex", "body.tex", "chapters/methods.tex"]
    tree = parse_tex_to_tree(concatenate_compilation_tex(sources))
    assert _texts(tree, "heading") == ["Body", "Method"]
    assert any("Nested file is compiled" in s for s in _texts(tree, "sentence"))


def test_thebibliography_and_appendix_switch_excluded_from_tree():
    tex = r"""
\documentclass{article}
\begin{document}
\section{Results}
Accuracy is high.

\appendix
\section{Proofs}
The bound holds.

\begin{thebibliography}{9}
\bibitem{x} Doe, J. A title. 2020.
\end{thebibliography}
\end{document}
"""
    tree = parse_tex_to_tree(tex)
    kinds = _kinds(tree)
    assert "appendix" in kinds
    joined = " ".join(_texts(tree, "sentence"))
    assert "Accuracy is high" in joined
    assert "The bound holds" in joined
    assert "Doe" not in joined
    proofs = [c for c in tree.children if c.content == "Proofs"]
    assert proofs and proofs[0].kind == "appendix"


def test_display_brackets_and_align():
    tex = r"""
\begin{document}
\section{Math}
Start here.
\[ a = b \]
\begin{align}
x &= 1 \\
y &= 2
\end{align}
Done now.
\end{document}
"""
    tree = parse_tex_to_tree(tex)
    formulas = _texts(tree, "formula")
    assert any(r"\[" in f or "a = b" in f for f in formulas)
    assert any("align" in f for f in formulas)
    assert any(s.startswith("Done") for s in _texts(tree, "sentence"))
