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


# --------------------------------------------------------------------------- #
# STR005: a one-word heading is not evidence of a house style
# --------------------------------------------------------------------------- #
#
# Found by running the checker on the thesis template, whose section headings
# are the ordinary ones -- Motivation, Participants, Apparatus, Analysis. Only
# the words after the first tell the two conventions apart, because the first
# is capitalised in both, so a heading with no such word decides nothing. The
# rule used to count those as sentence case and then report them for being in
# the minority it had just invented.

def _sections(*titles: str) -> str:
    return "\n\n".join(BS + "section{" + t + "}\n\nSome text in the section."
                       for t in titles)


def test_one_word_headings_are_not_reported(tmp_path):
    body = _sections("Motivation", "Participants", "Apparatus", "Analysis",
                     "Study Design", "Design Implications")
    assert "STR005" not in fired(check(build(tmp_path, body), only=["STR005"]))


def test_headings_whose_only_other_word_is_short_are_not_reported(tmp_path):
    # "Research Gap" -- "Gap" is filtered out as too short to carry the signal.
    body = _sections("Research Gap", "Future Work", "Related Work", "Study Design",
                     "Design Implications", "Summary of Contributions")
    assert "STR005" not in fired(check(build(tmp_path, body), only=["STR005"]))


def test_a_genuine_mixture_is_still_reported(tmp_path):
    body = _sections("Study Design", "Design Implications", "Summary of Contributions",
                     "Related Work Overview", "The odd one out here")
    result = check(build(tmp_path, body), only=["STR005"])
    assert "STR005" in fired(result)
    assert [f for f in result.findings if "odd one out" in f.message]


def test_undecidable_headings_do_not_swing_the_majority(tmp_path):
    # Three sentence-case headings decide the house style; the one-word
    # headings must not outvote them into Title Case.
    body = _sections("Motivation", "Analysis", "Apparatus", "Participants",
                     "The study design", "The design implications",
                     "The summary of contributions")
    result = check(build(tmp_path, body), only=["STR005"])
    assert not [f for f in result.findings if "study design" in f.message.lower()]


# --------------------------------------------------------------------------- #
# REF008: \autoref is not appropriate for sections
# --------------------------------------------------------------------------- #
#
# \autoref takes the word from the level of the thing labelled, not from the
# word the author wrote. A \subsection prints "Subsection 3.2.1" where the
# convention is "Section" at every depth, and a reference into the appendix
# prints "Chapter". Demanding \autoref there would demand a change to the
# printed text, which is a house-style decision and not a mistake.

def test_a_section_reference_is_left_alone(tmp_path):
    root = build(tmp_path, "Section~" + BS + "ref{sec:i} explains them.")
    assert "REF008" not in fired(check(root, only=["REF008"]))


def test_appendix_and_subsection_references_are_left_alone(tmp_path):
    body = ("Appendix~" + BS + "ref{app:a} lists the items, and "
            "Subsection~" + BS + "ref{sec:b} explains them.")
    assert "REF008" not in fired(check(build(tmp_path, body), only=["REF008"]))


def test_a_figure_reference_is_still_reported(tmp_path):
    root = build(tmp_path, "As shown in Figure~" + BS + "ref{fig:a}, it holds.")
    assert "REF008" in fired(check(root, only=["REF008"]))


def test_a_doubled_word_is_reported_even_for_a_section(tmp_path):
    # \autoref supplies the word itself, so this prints it twice whatever the
    # house style is. That is an outright error, not a preference.
    root = build(tmp_path, "Section~" + BS + "autoref{sec:i} prints it twice.")
    result = check(root, only=["REF008"])
    assert "REF008" in fired(result)
    assert any("twice" in f.message for f in result.findings)


def test_sections_can_be_opted_back_in(tmp_path):
    # A document that has redefined \subsectionautorefname can ask for it.
    root = build(tmp_path, "Section~" + BS + "ref{sec:i} explains them.")
    result = check(root, only=["REF008"], rules={"REF008": {"sections": True}})
    assert "REF008" in fired(result)


def test_a_missing_tie_on_a_section_is_still_reported(tmp_path):
    # The hole this would otherwise leave: REF004 used to stand aside entirely
    # whenever REF008 was enabled, so with REF008 silent on sections nothing
    # would report "Section \ref" at all.
    root = build(tmp_path, "Section " + BS + "ref{sec:i} has no tie.")
    assert "REF004" in fired(check(root, only=["REF004", "REF008"]))


def test_a_missing_tie_on_a_figure_defers_to_ref008(tmp_path):
    root = build(tmp_path, "Figure " + BS + "ref{fig:a} has no tie.")
    result = check(root, only=["REF004", "REF008"])
    assert "REF008" in fired(result)
    assert "REF004" not in fired(result)


# --------------------------------------------------------------------------- #
# ANON002: acmart removes its own acks environment
# --------------------------------------------------------------------------- #
#
# From acmart.cls:
#
#     \if@ACM@anonymous
#       \excludecomment{anonsuppress}
#       \excludecomment{acks}
#
# The content is not typeset at all, so a reviewer never sees it. Reporting it
# reports the correct construct as a mistake.

def _acmart(tmp_path, body, options="manuscript,screen,review,anonymous"):
    doc = (BS + "documentclass[" + options + "]{acmart}" + chr(10)
           + BS + "begin{document}" + chr(10) + body + chr(10)
           + BS + "end{document}" + chr(10))
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline=chr(10))
    return str(tmp_path)


ACKS = (BS + "begin{acks}" + chr(10)
        + "We thank all study participants." + chr(10)
        + BS + "end{acks}")


def test_acks_under_the_anonymous_option_is_not_reported(tmp_path):
    root = _acmart(tmp_path, ACKS)
    assert "ANON002" not in fired(check(root, only=["ANON002"], profile="paper-anonymous"))


def test_acks_without_the_anonymous_option_is_still_reported(tmp_path):
    # The class only removes it when the option is actually set. Anonymous
    # stage from the profile alone is not the same thing.
    root = _acmart(tmp_path, ACKS, options="manuscript,screen,review")
    assert "ANON002" in fired(check(root, only=["ANON002"], profile="paper-anonymous"))


def test_an_acknowledgements_section_is_still_reported(tmp_path):
    # Written as a plain section, acmart does not remove it, so it reaches the
    # reviewer and the rule must say so.
    body = BS + "section{Acknowledgements}" + chr(10) + "We thank the participants."
    root = _acmart(tmp_path, body)
    assert "ANON002" in fired(check(root, only=["ANON002"], profile="paper-anonymous"))


def test_a_funder_named_inside_acks_is_not_reported(tmp_path):
    body = (BS + "begin{acks}" + chr(10)
            + "This work was funded by the Deutsche Forschungsgemeinschaft." + chr(10)
            + BS + "end{acks}")
    root = _acmart(tmp_path, body)
    assert "ANON004" not in fired(check(root, only=["ANON004"], profile="paper-anonymous"))


def test_a_funder_named_in_the_body_is_still_reported(tmp_path):
    body = "This work was funded by the Deutsche Forschungsgemeinschaft."
    root = _acmart(tmp_path, body)
    assert "ANON004" in fired(check(root, only=["ANON004"], profile="paper-anonymous"))


def test_a_repository_link_inside_anonsuppress_is_not_reported(tmp_path):
    body = (BS + "begin{anonsuppress}" + chr(10)
            + "Our code is at https://github.com/mcolley/study for review." + chr(10)
            + BS + "end{anonsuppress}")
    root = _acmart(tmp_path, body)
    assert "ANON003" not in fired(check(root, only=["ANON003"], profile="paper-anonymous"))


def test_a_repository_link_in_the_body_is_still_reported(tmp_path):
    body = "Our code is at https://github.com/mcolley/study for review."
    root = _acmart(tmp_path, body)
    assert "ANON003" in fired(check(root, only=["ANON003"], profile="paper-anonymous"))


# --------------------------------------------------------------------------- #
# ABB004: names of technologies and standards need no expansion
# --------------------------------------------------------------------------- #

def test_protocol_and_format_names_need_no_introduction(tmp_path):
    body = ("The client speaks TCP and UDP, exchanges JSON over HTTPS, "
            "and stores the result as a PDF on an SSD.")
    assert "ABB004" not in fired(check(build(tmp_path, body), only=["ABB004"]))


def test_standards_bodies_need_no_introduction(tmp_path):
    body = "The format follows an ISO standard, an IETF RFC and an ANSI profile."
    assert "ABB004" not in fired(check(build(tmp_path, body), only=["ABB004"]))


def test_domain_jargon_is_still_reported(tmp_path):
    # The whole point of the rule: the outside examiner does not know these,
    # so they must not be in the built-in list.
    body = "The ADAS relies on the eHMI, and the TOR was issued by the LSTM model."
    reported = {f.data["acronym"] for f in check(build(tmp_path, body), only=["ABB004"]).findings}
    assert {"ADAS", "TOR", "LSTM"} <= reported


def test_the_technology_list_holds_only_matchable_entries():
    # Only runs of 2-9 capitals ever reach ABB004, so an entry with a digit or
    # a lower-case letter would be dead weight that nobody would ever notice.
    from mechcheck.rules.abbrev import _TECHNOLOGY
    import re
    bad = [w for w in _TECHNOLOGY if not re.fullmatch(r"[A-Z]{2,9}", w)]
    assert not bad, bad
