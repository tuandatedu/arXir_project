"""Regression: one-block \\bibitem must not treat journal abbreviations as title breaks."""

from src.m2_parsing.bibitem import extract_bibitems


def _wrap(body: str) -> str:
    return r"\begin{thebibliography}{99}" + body + r"\end{thebibliography}"


def test_andrews_dalton_trans_volume_is_not_title():
    rows = extract_bibitems(_wrap(
        r"\bibitem{Andrews_DT_15} R. L. Andrews, A. M. Heyns, and P. M. Woodward, "
        r"Raman studies of A$_2$MWO$_6$ tungstate double perovskites, "
        r"Dalton Trans. {\bf 44}, 10700 (2015)."
    ))
    assert rows[0]["citation_key"] == "Andrews_DT_15"
    assert rows[0]["title"] == r"Raman studies of A$_2$MWO$_6$ tungstate double perovskites"
    assert rows[0]["authors"] == ["R. L. Andrews", "A. M. Heyns", "P. M. Woodward"]
    assert rows[0]["year"] == 2015
    assert rows[0]["journal"] == "Dalton Trans"
    assert rows[0]["title"] != "44, 10700 (2015)"


def test_dhs_annals_of_math_volume_is_not_title():
    rows = extract_bibitems(_wrap(
        r"\bibitem{DHS} E. S. Devinatz, M. J. Hopkins, and J. H. Smith, "
        r"Nilpotence and stable homotopy, Annals of Math. {\bf 128} (1988) pp 207-242."
    ))
    assert rows[0]["citation_key"] == "DHS"
    assert rows[0]["title"] == "Nilpotence and stable homotopy"
    assert rows[0]["authors"] == ["E. S. Devinatz", "M. J. Hopkins", "J. H. Smith"]
    assert rows[0]["year"] == 1988
    assert rows[0]["journal"] == "Annals of Math"
    assert not any("Nilpotence" in name or "stable homotopy" in name for name in rows[0]["authors"])
    assert rows[0]["title"] != "128 (1988) pp 207-242"


def test_phys_rev_lett_chained_abbreviations():
    rows = extract_bibitems(_wrap(
        r"\bibitem{prl} A. B. Author, C. D. Writer, and E. F. Last, "
        r"A measured spectrum of something, Phys. Rev. Lett. {\bf 123}, 4567 (2020)."
    ))
    assert rows[0]["title"] == "A measured spectrum of something"
    assert rows[0]["authors"] == ["A. B. Author", "C. D. Writer", "E. F. Last"]
    assert rows[0]["journal"] == "Phys. Rev. Lett"
    assert rows[0]["year"] == 2020


def test_sentence_style_one_block_still_keeps_title():
    rows = extract_bibitems(_wrap(r"\bibitem{ref} J. Doe. A Study. 2020. doi:10.1234/test."))
    assert rows[0]["title"] == "A Study"
    assert rows[0]["authors"] == ["J. Doe"]
    assert rows[0]["year"] == 2020
    assert rows[0]["doi"] == "10.1234/test"
