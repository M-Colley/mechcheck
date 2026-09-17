"""One name per concept: the TRM family, in both directions.

The rules that only report a fact (TRM001, TRM003, TRM004, TRM005) must stay
quiet wherever English itself explains the difference -- "a real-time system"
beside "runs in real time", a defined term in Title Case beside the ordinary
adjective. The one rule that prescribes (TRM002) fires only where a project
has written its choice down, and its automatic substitution has to survive
plurals, capitals and the article in front of it.

The browser engine asserts the same behaviours in browser/test-engine.mjs.
"""

from __future__ import annotations

import os

import mechcheck.rules  # noqa: F401
from mechcheck import fixer
from mechcheck.config import Config
from mechcheck.runner import run

BS = chr(92)
NL = chr(10)

VEHICLES = "  - prefer: automated vehicle" + NL + "    over: [self-driving car, driverless car]" + NL


def build(tmp_path, body: str, config: str = "", preamble: str = "") -> str:
    doc = (BS + "documentclass{article}" + NL + preamble
           + BS + "begin{document}" + NL + body + NL + BS + "end{document}" + NL)
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline=NL)
    if config:
        (tmp_path / "mechcheck.yaml").write_text(config, encoding="utf-8", newline=NL)
    return str(tmp_path)


def check(root: str, only=None, **overrides):
    config = Config.load(root, overrides={"max_per_rule": 0, **overrides})
    return run(root, config, only=only, offline=True, baseline=None)


def fired(result) -> set:
    return {f.rule for f in result.findings}


def of(result, rule_id: str) -> list:
    return [f for f in result.findings if f.rule == rule_id]


def fix_and_read(root: str) -> str:
    config = Config.load(root, overrides={"max_per_rule": 0})
    fixer.fix(root, config, run, offline=True)
    with open(os.path.join(root, "main.tex"), encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# TRM001: two names, no prescription
# --------------------------------------------------------------------------- #

def test_two_names_for_one_concept_are_reported(tmp_path):
    body = ("The automated vehicle stopped. Another automated vehicle waited. "
            "The self-driving car did not.")
    result = check(build(tmp_path, body), only=["TRM001"])
    assert len(of(result, "TRM001")) == 1
    assert "automated vehicle" in result.findings[0].message


def test_the_majority_name_is_the_one_reported_against(tmp_path):
    body = ("The self-driving car stopped. Another self-driving car waited. "
            "The automated vehicle did not.")
    result = check(build(tmp_path, body), only=["TRM001"])
    assert of(result, "TRM001")
    assert "self-driving car" in result.findings[0].message
    assert result.findings[0].data["majority"] == "self-driving car"


def test_one_name_used_throughout_is_not_reported(tmp_path):
    body = "The automated vehicle stopped. Another automated vehicle waited."
    assert "TRM001" not in fired(check(build(tmp_path, body), only=["TRM001"]))


def test_a_plural_counts_as_the_same_name(tmp_path):
    body = "Automated vehicles stopped. The automated vehicle waited."
    assert "TRM001" not in fired(check(build(tmp_path, body), only=["TRM001"]))


def test_a_phrase_does_not_match_across_masked_markup(tmp_path):
    """"study" here and "Participant" six lines later are not "study participant".

    The prose view masks commands to spaces, so an unbounded gap between the
    words of a phrase let two unrelated captions match as one term.
    """
    body = (BS + "caption{Results of the study}" + NL
            + BS + "begin{table}" + NL + "  " + BS + "centering" + NL
            + "  " + BS + "caption{Participant demographics}" + NL
            + BS + "end{table}" + NL + "Participants took part.")
    assert "TRM001" not in fired(check(build(tmp_path, body), only=["TRM001"]))


def test_a_phrase_may_still_wrap_across_one_line(tmp_path):
    body = ("The automated" + NL + "vehicle stopped. Another automated vehicle waited." + NL
            + "The self-driving car did not.")
    assert "TRM001" in fired(check(build(tmp_path, body), only=["TRM001"]))


def test_the_built_in_groups_can_be_switched_off(tmp_path):
    body = "The automated vehicle stopped. The self-driving car did not."
    config = "rules:" + NL + "  TRM001:" + NL + "    use_defaults: false" + NL
    assert "TRM001" not in fired(check(build(tmp_path, body, config), only=["TRM001"]))


def test_a_project_group_is_reported_without_a_preference(tmp_path):
    body = "The lead vehicle braked. The lead car braked. The lead car stopped."
    config = "terminology:" + NL + "  - variants: [lead vehicle, lead car]" + NL
    result = check(build(tmp_path, body, config), only=["TRM001"])
    assert len(of(result, "TRM001")) == 1
    assert result.findings[0].data["majority"] == "lead car"


# --------------------------------------------------------------------------- #
# TRM002: the project's own term, and the substitution
# --------------------------------------------------------------------------- #

def test_the_projects_term_is_enforced_when_configured(tmp_path):
    body = "The self-driving car stopped near the driverless car."
    config = "terminology:" + NL + VEHICLES
    result = check(build(tmp_path, body, config), only=["TRM002"])
    assert len(of(result, "TRM002")) == 2
    assert all("automated vehicle" in f.message for f in result.findings)


def test_trm001_stands_aside_where_trm002_speaks(tmp_path):
    body = "The self-driving car stopped. The automated vehicle did not."
    config = "terminology:" + NL + VEHICLES
    result = check(build(tmp_path, body, config), only=["TRM001", "TRM002"])
    assert fired(result) == {"TRM002"}


def test_nothing_is_prescribed_without_a_configured_preference(tmp_path):
    body = "The self-driving car stopped. The automated vehicle did not."
    assert "TRM002" not in fired(check(build(tmp_path, body), only=["TRM002"]))


def test_the_preferred_term_is_not_reported_against_itself(tmp_path):
    body = "The automated vehicle stopped. Another automated vehicle waited."
    config = "terminology:" + NL + VEHICLES
    assert "TRM002" not in fired(check(build(tmp_path, body, config), only=["TRM002"]))


def test_the_substitution_carries_case_and_number(tmp_path):
    body = ("Self-driving cars are common. The self-driving car stopped, and two" + NL
            + "driverless cars followed.")
    root = build(tmp_path, body, "terminology:" + NL + VEHICLES)
    text = fix_and_read(root)
    assert "Automated vehicles are common." in text
    assert "The automated vehicle stopped" in text
    assert "two" + NL + "automated vehicles followed." in text


def test_the_substitution_corrects_the_article(tmp_path):
    """Replacing the noun changes the sound the article has to agree with."""
    body = "A self-driving car waited. An autonomous car left. A driverless car too."
    config = ("terminology:" + NL + "  - prefer: automated vehicle" + NL
              + "    over: [self-driving car, driverless car, autonomous car]" + NL)
    text = fix_and_read(build(tmp_path, body, config))
    assert "An automated vehicle waited." in text
    assert "An automated vehicle left." in text
    assert "A automated" not in text


def test_an_article_behind_markup_is_left_alone(tmp_path):
    """Widening the edit blindly would swallow the command in between."""
    body = "We saw a " + BS + "emph{self-driving car} today."
    text = fix_and_read(build(tmp_path, body, "terminology:" + NL + VEHICLES))
    assert BS + "emph{automated vehicle}" in text
    assert "we saw a " in text.lower()


def test_an_article_that_already_agrees_is_untouched(tmp_path):
    body = "An autonomous car waited near a bus."
    config = ("terminology:" + NL + "  - prefer: automated vehicle" + NL
              + "    over: [autonomous car]" + NL)
    text = fix_and_read(build(tmp_path, body, config))
    assert "An automated vehicle waited near a bus." in text


def test_a_shouted_term_is_reported_but_not_rewritten(tmp_path):
    body = "THE SELF-DRIVING CAR stopped here today."
    result = check(build(tmp_path, body, "terminology:" + NL + VEHICLES), only=["TRM002"])
    assert of(result, "TRM002")
    assert result.findings[0].edit is None


def test_the_project_group_wins_over_the_built_in_one(tmp_path):
    """A configured variant leaves the built-in group, so only one rule speaks."""
    body = "The self-driving car stopped. The automated vehicle did not."
    config = ("terminology:" + NL + "  - prefer: self-driving car" + NL
              + "    over: [automated vehicle]" + NL)
    result = check(build(tmp_path, body, config), only=["TRM001", "TRM002"])
    assert fired(result) == {"TRM002"}
    assert "self-driving car" in result.findings[0].message


# --------------------------------------------------------------------------- #
# TRM003: one term, two spellings
# --------------------------------------------------------------------------- #

def test_hyphenated_and_open_spellings_are_reported(tmp_path):
    body = ("We used an eye-tracking device. The eye tracking data were noisy, "
            "and the eye-tracking setup worked.")
    result = check(build(tmp_path, body), only=["TRM003"])
    assert len(of(result, "TRM003")) == 1
    assert "eye-tracking" in result.findings[0].message


def test_the_modifier_rule_is_not_an_inconsistency(tmp_path):
    """"a real-time system" and "runs in real time" are both correct English."""
    body = "A real-time system ran it, and the logs were written in real time."
    assert "TRM003" not in fired(check(build(tmp_path, body), only=["TRM003"]))


def test_open_and_closed_spellings_are_reported(tmp_path):
    body = "The dataset was large. The data set contained samples. Another dataset."
    result = check(build(tmp_path, body), only=["TRM003"])
    assert len(of(result, "TRM003")) == 1
    assert "dataset" in result.findings[0].message


def test_closed_and_hyphenated_spellings_are_reported(tmp_path):
    body = "The model was nonlinear. A non-linear model fitted better than that."
    assert "TRM003" in fired(check(build(tmp_path, body), only=["TRM003"]))


def test_one_spelling_throughout_is_not_reported(tmp_path):
    body = "We used an eye-tracking device and the eye-tracking data were clean."
    assert "TRM003" not in fired(check(build(tmp_path, body), only=["TRM003"]))


def test_two_ordinary_words_are_not_a_compound(tmp_path):
    body = "The study group met. The other study group also met here today."
    assert "TRM003" not in fired(check(build(tmp_path, body), only=["TRM003"]))


# --------------------------------------------------------------------------- #
# TRM004: capitalised in some places and not others
# --------------------------------------------------------------------------- #

def test_a_term_capitalised_inconsistently_is_reported(tmp_path):
    body = ("The Participants arrived. Each Participants group waited. "
            "Then the participants sat down, and the participants began.")
    assert "TRM004" in fired(check(build(tmp_path, body), only=["TRM004"]))


def test_a_defined_term_in_title_case_is_not_a_slip(tmp_path):
    """"Automated Driving System" is a name; "automated" elsewhere is a word."""
    body = ("The Automated Driving System braked. The Automated Driving System "
            "stopped. An automated vehicle waited, and the automated bus left.")
    assert "TRM004" not in fired(check(build(tmp_path, body), only=["TRM004"]))


def test_a_word_that_merely_opens_a_sentence_is_not_capitalised_inconsistently(tmp_path):
    body = ("Participants arrived here. Participants waited there. "
            "The participants sat down, and the participants began the task.")
    assert "TRM004" not in fired(check(build(tmp_path, body), only=["TRM004"]))


def test_headings_may_be_in_title_case(tmp_path):
    body = (BS + "section{Driving Simulator Study}" + NL
            + "The simulator ran. The driving simulator ran again here." + NL
            + BS + "section{Driving Simulator Results}" + NL
            + "The driving simulator produced data, and the simulator stopped.")
    assert "TRM004" not in fired(check(build(tmp_path, body), only=["TRM004"]))


def test_capitalisation_is_not_compared_in_german(tmp_path):
    body = ("Die Teilnehmer kamen an. Alle Teilnehmer warteten dort. "
            "Dann sassen die teilnehmer und die teilnehmer begannen damit.")
    root = build(tmp_path, body)
    assert "TRM004" not in fired(check(root, only=["TRM004"], language="de"))


# --------------------------------------------------------------------------- #
# TRM005: the expansion that outlived its abbreviation
# --------------------------------------------------------------------------- #

def test_an_expansion_repeated_after_the_definition_is_reported(tmp_path):
    body = ("The Automated Driving System (ADS) is new. The ADS was tested." + NL
            + "The Automated Driving System braked. The Automated Driving System" + NL
            + "stopped. The Automated Driving System waited.")
    result = check(build(tmp_path, body), only=["TRM005"])
    assert "TRM005" in fired(result)
    assert result.findings[0].data["repeats"] == 3


def test_using_the_abbreviation_is_not_reported(tmp_path):
    body = ("The Automated Driving System (ADS) is new. The ADS was tested. "
            "The ADS braked. The ADS stopped. The ADS waited here.")
    assert "TRM005" not in fired(check(build(tmp_path, body), only=["TRM005"]))


def test_an_abbreviation_that_is_never_used_belongs_to_abb003(tmp_path):
    body = ("The Automated Driving System (ADS) is new." + NL
            + "The Automated Driving System braked. The Automated Driving System" + NL
            + "stopped. The Automated Driving System waited.")
    assert "TRM005" not in fired(check(build(tmp_path, body), only=["TRM005"]))


def test_a_second_definition_belongs_to_abb001(tmp_path):
    """Re-defining is ABB001's; re-expanding without the acronym is this rule's."""
    body = ("The Automated Driving System (ADS) is new. The ADS was tested." + NL
            + "The Automated Driving System (ADS) appears again here." + NL
            + "The Automated Driving System (ADS) and the ADS.")
    assert "TRM005" not in fired(check(build(tmp_path, body), only=["TRM005"]))


# --------------------------------------------------------------------------- #
# `mechcheck terms`
# --------------------------------------------------------------------------- #

def test_the_survey_offers_a_configuration_block(tmp_path, capsys):
    from mechcheck.cli import main

    body = ("The automated vehicle stopped. Another automated vehicle waited. "
            "The self-driving car did not. The eye-tracking device ran, and "
            "the eye tracking data were noisy.")
    code = main(["terms", build(tmp_path, body)])
    out = capsys.readouterr().out
    assert code == 0
    assert "terminology:" in out
    assert "prefer: automated vehicle" in out
    assert "self-driving car" in out
    assert "eye-tracking" in out


def test_the_survey_says_so_when_there_is_nothing_to_report(tmp_path, capsys):
    from mechcheck.cli import main

    main(["terms", build(tmp_path, "The automated vehicle stopped here today.")])
    assert "Nothing to report" in capsys.readouterr().out


def test_the_survey_marks_what_the_project_already_configured(tmp_path, capsys):
    from mechcheck.cli import main

    body = "The self-driving car stopped. The automated vehicle did not."
    main(["terms", build(tmp_path, body, "terminology:" + NL + VEHICLES)])
    out = capsys.readouterr().out
    assert "from your configuration" in out
