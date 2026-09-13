"""The rules added in September 2026, each tested in both directions.

Same discipline as test_rules.py: the negative cases are the ones that keep
the checker trustworthy, so every rule here has at least one input it must
leave alone. Where a rule carries an automatic fix, the fix is exercised too,
because a wrong fix deletes words from somebody's thesis.

The browser engine asserts the same behaviours in browser/test-engine.mjs.
"""

from __future__ import annotations

import os

import mechcheck.rules  # noqa: F401
from mechcheck import fixer
from mechcheck.config import Config
from mechcheck.model import Severity
from mechcheck.runner import run

BS = chr(92)
NL = chr(10)


def build(tmp_path, body: str, preamble: str = "", files: dict | None = None,
          cls: str = "article") -> str:
    doc = (BS + "documentclass{" + cls + "}" + NL + preamble
           + BS + "begin{document}" + NL + body + NL + BS + "end{document}" + NL)
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline=NL)
    for name, content in (files or {}).items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8", newline=NL)
    return str(tmp_path)


def check(root: str, only=None, build_dir=None, **overrides):
    config = Config.load(root, overrides={"max_per_rule": 0, **overrides})
    return run(root, config, only=only, offline=True, baseline=None, build_dir=build_dir)


def fired(result) -> set:
    return {f.rule for f in result.findings}


def of(result, rule_id: str) -> list:
    return [f for f in result.findings if f.rule == rule_id]


def fix_and_read(root: str, **overrides) -> str:
    config = Config.load(root, overrides={"max_per_rule": 0, **overrides})
    fixer.fix(root, config, run, offline=True)
    with open(os.path.join(root, "main.tex"), encoding="utf-8") as fh:
        return fh.read()


FIGURE = (BS + "begin{figure}" + BS + "includegraphics{%s}" + BS + "caption{A}"
          + BS + "label{fig:a}" + BS + "end{figure} See " + BS + "autoref{fig:a}.")


# --------------------------------------------------------------------------- #
# the helpers the file-name rules stand on
# --------------------------------------------------------------------------- #

def test_absolute_paths_are_recognised_and_macros_are_not():
    from mechcheck.texsource import is_absolute_path

    assert is_absolute_path("C:/Users/mark/plot.png")
    assert is_absolute_path("C:" + BS + "Users" + BS + "mark" + BS + "plot.png")
    assert is_absolute_path("/home/mark/plot.png")
    assert is_absolute_path("~/plot.png")
    assert not is_absolute_path("figures/plot.png")
    assert not is_absolute_path(BS + "figdir/plot")


def test_case_insensitive_lookup_reports_the_disk_spelling(tmp_path):
    from mechcheck.texsource import find_case_insensitive

    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "plot.png").write_bytes(b"png")
    assert find_case_insensitive(str(tmp_path), "Figures/Plot.PNG") == "figures/plot.png"
    assert find_case_insensitive(str(tmp_path), "figures/plot.png") == "figures/plot.png"
    assert find_case_insensitive(str(tmp_path), "figures/other.png") is None
    assert find_case_insensitive(str(tmp_path), "figures") is None   # a directory is not a file


def test_sentence_boundaries_respect_abbreviations():
    from mechcheck.texsource import sentence_starts_at

    text = "It works. Next one. Colley et al. said so; e.g. this. M. Colley wrote"
    assert sentence_starts_at(text, 0)
    assert sentence_starts_at(text, text.index("Next"))
    assert not sentence_starts_at(text, text.index("said"))
    assert not sentence_starts_at(text, text.index("this"))
    assert not sentence_starts_at(text, text.index("Colley wrote"))
    assert not sentence_starts_at(text, text.index("one"))


# --------------------------------------------------------------------------- #
# FIG012 / FIG008 / FIG015: where the graphics really are
# --------------------------------------------------------------------------- #

def test_case_mismatch_in_a_graphics_path_is_fig012_not_fig008(tmp_path):
    root = build(tmp_path, FIGURE % "Figures/Plot.png", files={"figures/plot.png": b"png"})
    result = check(root, only=["FIG008", "FIG012"])
    assert fired(result) == {"FIG012"}
    finding = result.findings[0]
    assert "figures/plot.png" in finding.message
    assert finding.edit is not None and finding.edit.replacement == "figures/plot.png"


def test_the_exact_spelling_passes(tmp_path):
    root = build(tmp_path, FIGURE % "figures/plot.png", files={"figures/plot.png": b"png"})
    assert fired(check(root, only=["FIG008", "FIG012"])) == set()


def test_an_upper_case_extension_is_fine_when_none_is_written(tmp_path):
    # pdflatex tries .PNG as well as .png when the author leaves the extension out.
    root = build(tmp_path, FIGURE % "figures/plot", files={"figures/plot.PNG": b"png"})
    assert fired(check(root, only=["FIG008", "FIG012"])) == set()


def test_a_genuinely_missing_graphic_is_still_fig008(tmp_path):
    root = build(tmp_path, FIGURE % "figures/nothing.png", files={"figures/plot.png": b"png"})
    assert fired(check(root, only=["FIG008", "FIG012"])) == {"FIG008"}


def test_the_case_fix_keeps_the_authors_extension_choice(tmp_path):
    root = build(tmp_path, FIGURE % "Figures/Plot", files={"figures/plot.png": b"png"})
    assert check(root, only=["FIG012"]).findings[0].edit.replacement == "figures/plot"
    assert BS + "includegraphics{figures/plot}" in fix_and_read(root)


def test_absolute_graphics_paths_are_fig015(tmp_path):
    for path in ("C:/Users/mark/Desktop/plot.png", "/home/mark/plot.png"):
        root = build(tmp_path, FIGURE % path)
        assert fired(check(root, only=["FIG008", "FIG012", "FIG015"])) == {"FIG015"}, path


def test_a_macro_built_path_is_neither_missing_nor_absolute(tmp_path):
    root = build(tmp_path, FIGURE % (BS + "figdir/plot"))
    assert fired(check(root, only=["FIG008", "FIG012", "FIG015"])) == set()


# --------------------------------------------------------------------------- #
# FIG013, FIG014
# --------------------------------------------------------------------------- #

def test_center_environment_inside_a_float(tmp_path):
    body = (BS + "begin{figure}" + BS + "begin{center}x" + BS + "end{center}" + BS + "caption{A}"
            + BS + "label{fig:a}" + BS + "end{figure} See " + BS + "autoref{fig:a}.")
    assert "FIG013" in fired(check(build(tmp_path, body), only=["FIG013"]))


def test_centering_is_the_accepted_form(tmp_path):
    body = (BS + "begin{figure}" + BS + "centering x" + BS + "caption{A}"
            + BS + "label{fig:a}" + BS + "end{figure} See " + BS + "autoref{fig:a}.")
    assert "FIG013" not in fired(check(build(tmp_path, body), only=["FIG013"]))


def test_a_float_referred_to_by_position(tmp_path):
    root = build(tmp_path, "The results are shown in the figure below, and the table above lists them.")
    assert len(of(check(root, only=["FIG014"]), "FIG014")) == 2


def test_a_numbered_reference_is_not_positional(tmp_path):
    root = build(tmp_path, "The results are shown in Figure~" + BS + "ref{fig:a} and " + BS + "autoref{tab:b}.")
    assert "FIG014" not in fired(check(root, only=["FIG014"]))


# --------------------------------------------------------------------------- #
# REF010, REF011
# --------------------------------------------------------------------------- #

def test_adjacent_citations_are_reported_and_merged(tmp_path):
    root = build(tmp_path, "Prior work~" + BS + "cite{a}" + BS + "cite{b} agrees with this.")
    result = check(root, only=["REF010"])
    assert len(of(result, "REF010")) == 1
    assert result.findings[0].edit.replacement == BS + "cite{a,b}"
    assert BS + "cite{a,b} agrees" in fix_and_read(root)


def test_a_chain_of_three_citations_is_one_finding(tmp_path):
    root = build(tmp_path, "Prior work~" + BS + "cite{a}, " + BS + "cite{b} " + BS + "cite{c} agrees.")
    result = check(root, only=["REF010"])
    assert len(of(result, "REF010")) == 1
    assert result.findings[0].edit.replacement == BS + "cite{a,b,c}"


def test_citations_joined_by_and_are_left_alone(tmp_path):
    root = build(tmp_path, "Both " + BS + "cite{a} and " + BS + "cite{b} agree.")
    assert "REF010" not in fired(check(root, only=["REF010"]))


def test_different_citation_commands_are_not_merged(tmp_path):
    root = build(tmp_path, "See " + BS + "citep{a}" + BS + "citet{b} for this.", cls="acmart")
    assert "REF010" not in fired(check(root, only=["REF010"]))


def test_a_citation_as_the_subject_of_a_sentence(tmp_path):
    root = build(tmp_path, "Some text here. " + BS + "cite{a} showed that this works.", cls="acmart")
    result = check(root, only=["REF011"])
    assert "REF011" in fired(result)
    assert "citet" in result.findings[0].fix


def test_a_sentence_opening_with_in_and_a_citation(tmp_path):
    root = build(tmp_path, "Some text here. In " + BS + "cite{a}, the authors argue this.")
    assert "REF011" in fired(check(root, only=["REF011"]))


def test_a_citation_after_a_name_is_not_a_noun(tmp_path):
    root = build(tmp_path, "Colley et al. " + BS + "cite{a} showed that this works.")
    assert "REF011" not in fired(check(root, only=["REF011"]))


def test_a_citation_mid_sentence_is_fine(tmp_path):
    root = build(tmp_path, "This was shown earlier " + BS + "cite{a} and confirmed since.")
    assert "REF011" not in fired(check(root, only=["REF011"]))


# --------------------------------------------------------------------------- #
# STY015 - STY020
# --------------------------------------------------------------------------- #

def test_typed_ellipsis_is_reported_and_fixed(tmp_path):
    root = build(tmp_path, "Wait for it... and then it happens.")
    assert "STY015" in fired(check(root, only=["STY015"]))
    assert "Wait for it" + BS + "dots{} and then" in fix_and_read(root)


def test_a_real_dots_command_is_fine(tmp_path):
    root = build(tmp_path, "Wait for it" + BS + "dots{} and then it happens.")
    assert "STY015" not in fired(check(root, only=["STY015"]))


def test_a_bare_url_is_reported(tmp_path):
    root = build(tmp_path, "The code is at https://github.com/x/y for review.")
    result = check(root, only=["STY016"])
    assert fired(result) == {"STY016"}
    assert "https://github.com/x/y" in result.findings[0].message
    assert result.findings[0].edit is None            # no url package to wrap with


def test_wrapped_urls_are_fine(tmp_path):
    preamble = BS + "usepackage{hyperref}" + NL
    body = ("See " + BS + "url{https://github.com/x/y} and "
            + BS + "href{https://example.org/a_b}{the page}.")
    assert "STY016" not in fired(check(build(tmp_path, body, preamble), only=["STY016"]))


def test_a_url_defined_in_the_preamble_is_fine(tmp_path):
    preamble = BS + "newcommand{" + BS + "repo}{https://github.com/x/y}" + NL
    assert "STY016" not in fired(check(build(tmp_path, "See " + BS + "repo.", preamble), only=["STY016"]))


def test_the_url_fix_wraps_when_hyperref_is_loaded(tmp_path):
    root = build(tmp_path, "The code is at https://github.com/x/y.", BS + "usepackage{hyperref}" + NL)
    assert BS + "url{https://github.com/x/y}." in fix_and_read(root)


def test_a_space_before_footnote_is_reported_and_closed(tmp_path):
    root = build(tmp_path, "A claim " + BS + "footnote{Source.} here.")
    assert "STY017" in fired(check(root, only=["STY017"]))
    assert "A claim" + BS + "footnote{Source.} here." in fix_and_read(root)


def test_an_attached_footnote_is_fine(tmp_path):
    root = build(tmp_path, "A claim" + BS + "footnote{Source.} here.")
    assert "STY017" not in fired(check(root, only=["STY017"]))


def test_a_sentence_starting_with_a_numeral(tmp_path):
    root = build(tmp_path, "We ran a study. 12 participants took part in it.")
    assert "STY018" in fired(check(root, only=["STY018"]))


def test_numbers_inside_a_sentence_are_fine(tmp_path):
    root = build(tmp_path, "We recruited 12 participants, and Table 3 lists the values.")
    assert "STY018" not in fired(check(root, only=["STY018"]))


def test_legacy_font_commands_and_double_dollars(tmp_path):
    root = build(tmp_path, "{" + BS + "bf Bold} text and $$x = 1$$ here.")
    result = check(root, only=["STY019"])
    assert len(of(result, "STY019")) == 2
    assert any("textbf" in f.fix for f in result.findings)


def test_modern_syntax_is_fine(tmp_path):
    body = (BS + "textbf{Bold} and " + BS + "begin{itemize}" + BS + "item one" + BS + "end{itemize}"
            + " and " + BS + "[ x = 1 " + BS + "] and " + BS + "ttfamily.")
    assert "STY019" not in fired(check(build(tmp_path, body), only=["STY019"]))


def test_mistyped_et_al_is_reported_and_fixed(tmp_path):
    root = build(tmp_path, "Colley et. al. showed it. Rukzio et al showed it too.")
    assert len(of(check(root, only=["STY020"]), "STY020")) == 2
    text = fix_and_read(root)
    assert "Colley et al. showed it. Rukzio et al. showed it too." in text


def test_correct_et_al_is_fine(tmp_path):
    root = build(tmp_path, "Colley et al.~" + BS + "cite{a} showed it, and they also agree.")
    assert "STY020" not in fired(check(root, only=["STY020"]))


# --------------------------------------------------------------------------- #
# STR010 - STR013
# --------------------------------------------------------------------------- #

def test_an_obsolete_package_names_its_replacement(tmp_path):
    result = check(build(tmp_path, "Text.", BS + "usepackage{subfigure}" + NL), only=["STR010"])
    assert "STR010" in fired(result)
    assert "subcaption" in result.findings[0].fix


def test_utf8x_is_obsolete(tmp_path):
    result = check(build(tmp_path, "Text.", BS + "usepackage[utf8x]{inputenc}" + NL), only=["STR010"])
    assert "STR010" in fired(result)


def test_current_packages_are_fine(tmp_path):
    preamble = BS + "usepackage{subcaption}" + NL + BS + "usepackage[utf8]{inputenc}" + NL
    assert "STR010" not in fired(check(build(tmp_path, "Text.", preamble), only=["STR010"]))


def test_a_package_loaded_twice_is_a_note(tmp_path):
    preamble = BS + "usepackage{graphicx}" + NL + BS + "usepackage{graphicx}" + NL
    result = check(build(tmp_path, "Text.", preamble), only=["STR011"])
    assert len(of(result, "STR011")) == 1
    assert result.findings[0].severity is Severity.INFO


def test_an_option_clash_is_a_warning(tmp_path):
    preamble = BS + "usepackage[table]{xcolor}" + NL + BS + "usepackage[dvipsnames]{xcolor}" + NL
    result = check(build(tmp_path, "Text.", preamble), only=["STR011"])
    assert result.findings[0].severity is Severity.WARN
    assert "option clash" in result.findings[0].message


def test_one_branch_of_a_switch_is_not_a_duplicate(tmp_path):
    # The thesis template does exactly this: draft options in one branch,
    # final options in the other. Only one of them is ever in the document.
    preamble = (BS + "def" + BS + "draftmode{}" + NL
                + BS + "ifdefined" + BS + "draftmode" + NL
                + "  " + BS + "usepackage[draft]{thesis}" + NL
                + BS + "else" + NL
                + "  " + BS + "usepackage[final]{thesis}" + NL
                + BS + "fi" + NL)
    assert "STR011" not in fired(check(build(tmp_path, "Text.", preamble), only=["STR011"]))


def test_conditional_spans_ignore_etoolbox_and_declarations():
    from mechcheck.texsource import conditional_spans

    text = (BS + "newif" + BS + "ifdraft " + BS + "iftoggle{x}{a}{b} "
            + BS + "ifdraft A " + BS + "else B " + BS + "fi tail")
    spans = conditional_spans(text)
    assert len(spans) == 1
    a, b = spans[0]
    assert text[a:b].startswith(BS + "ifdraft A") and text[a:b].endswith(BS + "fi")


def test_fontenc_may_be_loaded_per_encoding(tmp_path):
    preamble = BS + "usepackage[T1]{fontenc}" + NL + BS + "usepackage[T2A]{fontenc}" + NL
    assert "STR011" not in fired(check(build(tmp_path, "Text.", preamble), only=["STR011"]))


def test_cleveref_before_hyperref_is_reported(tmp_path):
    preamble = BS + "usepackage{cleveref}" + NL + BS + "usepackage{hyperref}" + NL
    assert "STR012" in fired(check(build(tmp_path, "Text.", preamble), only=["STR012"]))


def test_cleveref_after_hyperref_is_fine(tmp_path):
    preamble = BS + "usepackage{hyperref}" + NL + BS + "usepackage{cleveref}" + NL
    assert "STR012" not in fired(check(build(tmp_path, "Text.", preamble), only=["STR012"]))


def test_hyperref_loaded_out_of_sight_is_not_assumed_missing(tmp_path):
    preamble = BS + "usepackage{cleveref}" + NL
    assert "STR012" not in fired(check(build(tmp_path, "Text.", preamble), only=["STR012"]))


def test_an_input_with_the_wrong_case_is_str013_not_str001(tmp_path):
    root = build(tmp_path, BS + "input{Chapters/Intro}", files={"chapters/intro.tex": "Intro text here."})
    result = check(root, only=["STR001", "STR013"])
    assert fired(result) == {"STR013"}
    assert "chapters/intro.tex" in result.findings[0].message


def test_an_exact_input_is_fine(tmp_path):
    root = build(tmp_path, BS + "input{chapters/intro}", files={"chapters/intro.tex": "Intro text here."})
    assert fired(check(root, only=["STR001", "STR013"])) == set()


def test_an_absolute_input_is_str013(tmp_path):
    root = build(tmp_path, BS + "input{C:/Users/mark/thesis/intro.tex}")
    result = check(root, only=["STR001", "STR013"])
    assert fired(result) == {"STR013"}
    assert "absolute" in result.findings[0].message


def test_a_missing_input_is_still_str001(tmp_path):
    root = build(tmp_path, BS + "input{chapters/nowhere}", files={"chapters/intro.tex": "Intro."})
    assert fired(check(root, only=["STR001", "STR013"])) == {"STR001"}


# --------------------------------------------------------------------------- #
# BIB013 - BIB017
# --------------------------------------------------------------------------- #

def bibdoc(tmp_path, bib: str) -> str:
    return build(tmp_path, "Cited~" + BS + "cite{k1}." + NL + BS + "bibliography{refs}",
                 files={"refs.bib": bib})


def entry(key="k1", **fields) -> str:
    fields = {"author": "Doe, Jane", "title": "A Quiet Title", "year": "2020", **fields}
    body = "," + NL.join(f"  {name} = {{{value}}}," for name, value in fields.items())
    return "@inproceedings{" + key + body + NL + "}" + NL


def test_booktitle_starting_with_in(tmp_path):
    root = bibdoc(tmp_path, entry(booktitle="In Proceedings of the CHI Conference"))
    assert "BIB013" in fired(check(root, only=["BIB013"]))


def test_booktitles_that_merely_start_with_in_letters_are_fine(tmp_path):
    for booktitle in ("Proceedings of the CHI Conference", "Interaction Design and Children"):
        root = bibdoc(tmp_path, entry(booktitle=booktitle))
        assert "BIB013" not in fired(check(root, only=["BIB013"])), booktitle


def test_a_title_in_capitals(tmp_path):
    root = bibdoc(tmp_path, entry(title="A STUDY OF VERY LOUD TITLES", booktitle="CHI"))
    assert "BIB014" in fired(check(root, only=["BIB014"]))


def test_an_ordinary_title_is_fine(tmp_path):
    root = bibdoc(tmp_path, entry(title="A Study of the ACM and IEEE Styles", booktitle="CHI"))
    assert "BIB014" not in fired(check(root, only=["BIB014"]))


def test_a_url_that_repeats_the_doi(tmp_path):
    root = bibdoc(tmp_path, entry(booktitle="CHI", doi="10.1145/1.2", url="https://doi.org/10.1145/1.2"))
    assert "BIB015" in fired(check(root, only=["BIB015"]))


def test_a_url_to_somewhere_else_is_fine(tmp_path):
    root = bibdoc(tmp_path, entry(booktitle="CHI", doi="10.1145/1.2", url="https://example.org/paper"))
    assert "BIB015" not in fired(check(root, only=["BIB015"]))


def test_a_title_ending_with_a_period(tmp_path):
    root = bibdoc(tmp_path, entry(title="A Quiet Title.", booktitle="CHI"))
    assert "BIB016" in fired(check(root, only=["BIB016"]))


def test_titles_ending_in_an_initial_or_nothing_are_fine(tmp_path):
    for title in ("A Quiet Title", "Proceedings of Part A.", "Is it? Yes!"):
        root = bibdoc(tmp_path, entry(title=title, booktitle="CHI"))
        assert "BIB016" not in fired(check(root, only=["BIB016"])), title


def test_a_duplicate_citation_key(tmp_path):
    root = bibdoc(tmp_path, entry(booktitle="CHI") + entry(key="K1", booktitle="UIST"))
    result = check(root, only=["BIB017"])
    assert len(of(result, "BIB017")) == 1
    assert result.findings[0].severity is Severity.ERROR


def test_distinct_keys_are_fine(tmp_path):
    root = bibdoc(tmp_path, entry(booktitle="CHI") + entry(key="k2", booktitle="UIST"))
    assert "BIB017" not in fired(check(root, only=["BIB017"]))


# --------------------------------------------------------------------------- #
# LOG010, LOG011
# --------------------------------------------------------------------------- #

LOG_HEAD = "This is pdfTeX, Version 3.141592653-2.6-1.40.29 (TeX Live 2026)" + NL


def with_log(tmp_path, body: str) -> str:
    root = build(tmp_path, "Text here.")
    (tmp_path / "main.log").write_text(LOG_HEAD + body, encoding="utf-8", newline=NL)
    return root


def test_a_float_too_large_for_the_page(tmp_path):
    root = with_log(tmp_path, "LaTeX Warning: Float too large for page by 31.5pt on input line 88." + NL)
    result = check(root, only=["LOG010"])
    assert "LOG010" in fired(result)
    assert result.findings[0].line == 88


def test_a_token_hyperref_could_not_put_in_a_bookmark(tmp_path):
    root = with_log(tmp_path, "Package hyperref Warning: Token not allowed in a PDF string (Unicode):" + NL
                    + "(hyperref)                removing `" + BS + "cite' on input line 12." + NL)
    result = check(root, only=["LOG011"])
    assert "LOG011" in fired(result)
    assert "cite" in result.findings[0].message and result.findings[0].line == 12


def test_a_clean_log_reports_neither(tmp_path):
    root = with_log(tmp_path, "Output written on main.pdf (3 pages)." + NL)
    assert fired(check(root, only=["LOG010", "LOG011"])) == set()


# --------------------------------------------------------------------------- #
# POL010
# --------------------------------------------------------------------------- #

STUDY = ("Participants completed a questionnaire during the user study, "
         "and each participant was thanked afterwards.")


def test_a_study_that_never_states_its_sample_size(tmp_path):
    root = build(tmp_path, STUDY + " We report the results below in prose.")
    assert "POL010" in fired(check(root, only=["POL010"]))


def test_a_stated_count_satisfies_the_rule(tmp_path):
    for sentence in (" We recruited 24 participants.", " The sample (N = 24) was balanced.",
                     " Twenty-four participants took part.", " We recruited 24 female participants."):
        root = build(tmp_path, STUDY + sentence)
        assert "POL010" not in fired(check(root, only=["POL010"])), sentence

