"""Regression tests for false positives found on a real paper.

Every case here was reported wrongly by the checker on an actual ACM paper.
They are the most valuable tests in the suite: a checker people are asked to
satisfy spends its credibility on wrong findings, and `REF009` in particular
carried an auto-fix, so its mistakes would have deleted words from the paper.
"""

from __future__ import annotations

import mechcheck.rules  # noqa: F401
from mechcheck.config import Config
from mechcheck.runner import run

BS = chr(92)


def build(tmp_path, body: str, cls: str = "acmart") -> str:
    doc = (BS + "documentclass{" + cls + "}\n"
           + BS + "begin{document}\n" + body + "\n" + BS + "end{document}\n")
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline="\n")
    return str(tmp_path)


def check(root: str, only=None, **overrides):
    config = Config.load(root, overrides={"max_per_rule": 0, **overrides})
    return run(root, config, only=only, offline=True, baseline=None)


def fired(result) -> set:
    return {f.rule for f in result.findings}


# --------------------------------------------------------------------------- #
# REF009: a noun before a citation is not an author
# --------------------------------------------------------------------------- #

def test_a_common_noun_before_a_citation_is_not_a_name(tmp_path):
    root = build(tmp_path, "We used the Questionnaire~" + BS + "cite{a} and the Scale~" + BS + "cite{b}.")
    assert "REF009" not in fired(check(root, only=["REF009"]))


def test_an_acronym_before_a_citation_is_not_a_name(tmp_path):
    body = ("We used ANOVA~" + BS + "cite{a}, VR~" + BS + "cite{b} and ADMS~" + BS + "cite{c}.")
    assert "REF009" not in fired(check(build(tmp_path, body), only=["REF009"]))


def test_et_al_is_still_reported(tmp_path):
    root = build(tmp_path, "Colley et al.~" + BS + "cite{a} showed this.")
    assert "REF009" in fired(check(root, only=["REF009"]))


def test_two_surnames_are_still_reported(tmp_path):
    root = build(tmp_path, "Rukzio and Colley~" + BS + "cite{a} disagree.")
    assert "REF009" in fired(check(root, only=["REF009"]))


def test_single_names_can_be_switched_back_on(tmp_path):
    root = build(tmp_path, "Bazilinskyy~" + BS + "cite{a} measured it.")
    assert "REF009" not in fired(check(root, only=["REF009"]))
    louder = check(root, only=["REF009"],
                   rules={"REF009": {"include_single_names": True}})
    assert "REF009" in fired(louder)


def test_a_wrong_ref009_never_carries_an_auto_fix(tmp_path):
    """The edit deletes the matched words, so a false positive would corrupt text."""
    root = build(tmp_path, "We used the Questionnaire~" + BS + "cite{a}.")
    for f in check(root, only=["REF009"]).findings:
        assert f.edit is None or "Questionnaire" not in f.edit.replacement


# --------------------------------------------------------------------------- #
# REF002: section labels exist to be referenced *if needed*
# --------------------------------------------------------------------------- #

def test_unreferenced_section_labels_are_not_reported(tmp_path):
    body = (BS + "section{Method}" + BS + "label{sec:method}\nText here for the section.\n"
            + BS + "section{Results}" + BS + "label{subsec:results}\nMore text here.")
    assert "REF002" not in fired(check(build(tmp_path, body), only=["REF002"]))


def test_other_unreferenced_labels_are_still_reported(tmp_path):
    body = "Some text." + BS + "label{eq:important}\nMore text follows here."
    assert "REF002" in fired(check(build(tmp_path, body), only=["REF002"]))


# --------------------------------------------------------------------------- #
# STR004: a section that opens onto a subsection is ordinary writing
# --------------------------------------------------------------------------- #

def test_a_section_opening_on_a_subsection_is_not_empty(tmp_path):
    body = (BS + "section{Related Work}\n"
            + BS + "subsection{Virtual reality in training}\n"
            "Plenty of real content lives here in the subsection, many words long.")
    assert "STR004" not in fired(check(build(tmp_path, body), only=["STR004"]))


def test_a_genuinely_empty_subtree_is_still_reported(tmp_path):
    body = (BS + "section{Placeholder}\n" + BS + "subsection{Also empty}\n"
            + BS + "section{Real}\nThis one has actual content written under it.")
    result = check(build(tmp_path, body), only=["STR004"])
    assert "STR004" in fired(result)
    assert any("Placeholder" in f.message for f in result.findings)


# --------------------------------------------------------------------------- #
# STR005: Title Case sections with sentence case subsections is a house style
# --------------------------------------------------------------------------- #

def test_title_case_sections_with_sentence_case_subsections(tmp_path):
    body = "\n".join([
        BS + "section{Related Work}", "Content for this one.",
        BS + "subsection{Virtual reality in training}", "Content here.",
        BS + "subsection{Command and control}", "Content here.",
        BS + "section{Phase II: Method}", "Content for this one.",
        BS + "subsection{Participants and procedure}", "Content here.",
        BS + "subsection{Apparatus and measures}", "Content here.",
        BS + "section{Phase II: Results}", "Content for this one.",
        BS + "section{Open Questions Remaining}", "Content for this one.",
    ])
    assert "STR005" not in fired(check(build(tmp_path, body), only=["STR005"]))


def test_a_genuine_inconsistency_within_one_level_is_reported(tmp_path):
    body = "\n".join([
        BS + "section{Introduction and aims}", "Content.",
        BS + "section{Method and materials}", "Content.",
        BS + "section{Results and findings}", "Content.",
        BS + "section{Discussion Of The Whole Study}", "Content.",
    ])
    assert "STR005" in fired(check(build(tmp_path, body), only=["STR005"]))


# --------------------------------------------------------------------------- #
# MET005, STY007, THE*
# --------------------------------------------------------------------------- #

def test_sections_that_are_short_by_design_are_exempt(tmp_path):
    long_body = " ".join(["content"] * 400)
    body = "\n".join([
        BS + "section{Introduction}", long_body,
        BS + "section{Method}", long_body,
        BS + "section{Results}", long_body,
        BS + "section{Discussion}", long_body,
        BS + "section{Open Science}", "The data are available on OSF at the link given.",
        BS + "section{Acknowledgements}", "We thank the participants for their time.",
    ])
    assert "MET005" not in fired(check(build(tmp_path, body), only=["MET005"]))


def test_a_genuinely_stunted_section_is_still_reported(tmp_path):
    long_body = " ".join(["content"] * 400)
    body = "\n".join([
        BS + "section{Introduction}", long_body,
        BS + "section{Method}", long_body,
        BS + "section{Results}", long_body,
        BS + "section{Discussion}", "Too short.",
    ])
    assert "MET005" in fired(check(build(tmp_path, body), only=["MET005"]))


def test_a_product_number_is_not_a_range(tmp_path):
    root = build(tmp_path, "The machine had a Core 7-1355 processor inside it.")
    assert "STY007" not in fired(check(root, only=["STY007"]))


def test_a_real_range_is_still_reported(tmp_path):
    root = build(tmp_path, "We recruited 10-20 participants for the study.")
    assert "STY007" in fired(check(root, only=["STY007"]))


def test_thesis_rules_do_not_fire_on_a_paper_class(tmp_path):
    root = build(tmp_path, "A paper, not a thesis.", cls="acmart")
    result = check(root, profile="thesis")
    assert not [f for f in result.findings if f.rule.startswith("THE")]


def test_thesis_rules_still_fire_on_a_thesis_class(tmp_path):
    root = build(tmp_path, BS + "chapter{One}\nText.", cls="scrbook")
    result = check(root, profile="thesis", only=["THE001", "THE005"])
    assert fired(result) == {"THE001", "THE005"}
