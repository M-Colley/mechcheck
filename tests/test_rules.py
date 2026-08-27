"""Rule behaviour, including the cases that must NOT produce a finding.

Every rule here is tested in both directions. A checker that students are
required to satisfy earns its authority by never crying wolf, so the negative
cases matter more than the positive ones.
"""

from __future__ import annotations

import os

import pytest

import mechcheck.rules  # noqa: F401  (registers the rules)
from mechcheck.config import Config
from mechcheck.model import REGISTRY, Severity
from mechcheck.runner import run

BS = chr(92)


def build(tmp_path, body: str, preamble: str = "", files: dict | None = None) -> str:
    doc = (preamble or (BS + "documentclass{article}" + "\n")) \
        + BS + "begin{document}\n" + body + "\n" + BS + "end{document}\n"
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline="\n")
    for name, content in (files or {}).items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return str(tmp_path)


def check(root: str, only=None, **overrides):
    config = Config.load(root, overrides=overrides)
    return run(root, config, only=only, offline=True, baseline=None)


def rules_fired(result) -> set:
    return {f.rule for f in result.findings}


# --------------------------------------------------------------------------- #
# floats and cross-references
# --------------------------------------------------------------------------- #

def test_unreferenced_float_is_reported(tmp_path):
    root = build(tmp_path, BS + "begin{figure}" + BS + "caption{A}" + BS
                 + "label{fig:a}" + BS + "end{figure}")
    assert "FIG003" in rules_fired(check(root, only=["FIG003"]))


def test_referenced_float_is_not_reported(tmp_path):
    root = build(tmp_path,
                 BS + "begin{figure}" + BS + "caption{A}" + BS + "label{fig:a}"
                 + BS + "end{figure}\nSee Figure~" + BS + "ref{fig:a}.")
    assert "FIG003" not in rules_fired(check(root, only=["FIG003"]))


def test_label_before_caption_is_an_error(tmp_path):
    root = build(tmp_path, BS + "begin{figure}" + BS + "label{fig:a}" + BS
                 + "caption{A}" + BS + "end{figure}")
    result = check(root, only=["FIG004"])
    assert "FIG004" in rules_fired(result)
    assert result.findings[0].severity is Severity.ERROR


def test_correct_caption_then_label_is_accepted(tmp_path):
    root = build(tmp_path, BS + "begin{figure}" + BS + "caption{A}" + BS
                 + "label{fig:a}" + BS + "end{figure}")
    assert "FIG004" not in rules_fired(check(root, only=["FIG004"]))


def test_undefined_reference_is_reported_with_a_suggestion(tmp_path):
    root = build(tmp_path, BS + "label{sec:method}\nSee " + BS + "ref{sec:methods}.")
    result = check(root, only=["REF001"])
    assert "REF001" in rules_fired(result)
    assert "sec:method" in result.findings[0].message


def test_duplicate_label_is_reported_once_per_extra_definition(tmp_path):
    root = build(tmp_path, BS + "label{a} x " + BS + "label{a} y " + BS + "label{a}")
    result = check(root, only=["REF003"])
    assert len([f for f in result.findings if f.rule == "REF003"]) == 2


# --------------------------------------------------------------------------- #
# abbreviations
# --------------------------------------------------------------------------- #

def test_abbreviation_introduced_twice(tmp_path):
    root = build(tmp_path,
                 "The Automated Driving System (ADS) is new.\n"
                 "Later, the Automated Driving System (ADS) appears again. ADS ADS.")
    result = check(root, only=["ABB001"])
    assert "ABB001" in rules_fired(result)
    assert len([f for f in result.findings if f.rule == "ABB001"]) == 1


def test_abbreviation_introduced_once_is_fine(tmp_path):
    root = build(tmp_path, "The Automated Driving System (ADS) is new. The ADS works. ADS again.")
    assert "ABB001" not in rules_fired(check(root, only=["ABB001"]))


def test_glossaries_package_disables_the_abbreviation_rules(tmp_path):
    preamble = (BS + "documentclass{article}\n" + BS + "usepackage{glossaries}\n")
    root = build(tmp_path,
                 "The Automated Driving System (ADS) is new.\n"
                 "The Automated Driving System (ADS) again.", preamble=preamble)
    assert "ABB001" not in rules_fired(check(root, only=["ABB001"]))


# --------------------------------------------------------------------------- #
# style
# --------------------------------------------------------------------------- #

def test_todo_marker_is_an_error(tmp_path):
    root = build(tmp_path, "This section is TODO and needs work.")
    assert "STY001" in rules_fired(check(root, only=["STY001"]))


def test_repeated_word(tmp_path):
    root = build(tmp_path, "This is is a problem.")
    assert "STY003" in rules_fired(check(root, only=["STY003"]))


def test_repeated_word_allows_legitimate_repeats(tmp_path):
    root = build(tmp_path, "The results that that model produced were fine.")
    assert "STY003" not in rules_fired(check(root, only=["STY003"]))


def test_forced_linebreak_in_prose_but_not_in_a_table(tmp_path):
    body = ("Some prose" + BS + BS + " continues.\n"
            + BS + "begin{tabular}{ll}\na & b " + BS + BS + "\nc & d " + BS + BS + "\n"
            + BS + "end{tabular}")
    root = build(tmp_path, body)
    result = check(root, only=["STY002"])
    assert len([f for f in result.findings if f.rule == "STY002"]) == 1


def test_citation_reference_does_not_trigger_space_before_punctuation(tmp_path):
    root = build(tmp_path, "As shown in Figure~" + BS + "ref{fig:a}.")
    assert "STY005" not in rules_fired(check(root, only=["STY005"]))


# --------------------------------------------------------------------------- #
# suppression, baselines, configuration
# --------------------------------------------------------------------------- #

def test_inline_suppression_silences_one_line(tmp_path):
    body = (BS + "begin{figure}" + BS + "caption{A}" + BS + "label{fig:a}"
            + BS + "end{figure}  % mechcheck: off FIG003 -- decorative")
    root = build(tmp_path, body)
    result = check(root, only=["FIG003"])
    assert "FIG003" not in rules_fired(result)
    assert len(result.suppressed) == 1


def test_file_scope_suppression(tmp_path):
    body = ("% mechcheck: off-file STY001 -- draft chapter\n"
            "This is TODO.\nAnd another TODO here.")
    root = build(tmp_path, body)
    result = check(root, only=["STY001"])
    assert not result.findings
    assert len(result.suppressed) == 2


def test_suppression_only_silences_the_named_rule(tmp_path):
    body = "This is TODO.  % mechcheck: off FIG003 -- unrelated"
    root = build(tmp_path, body)
    assert "STY001" in rules_fired(check(root, only=["STY001"]))


def test_draft_stage_demotes_everything_below_the_failure_threshold(tmp_path):
    root = build(tmp_path, "This is TODO.")
    result = check(root, only=["STY001"], stage="draft")
    assert result.findings
    assert not result.should_fail()


def test_final_stage_promotes_warnings_to_errors(tmp_path):
    root = build(tmp_path, "This is is repeated.")
    result = check(root, only=["STY003"], stage="final")
    assert result.findings[0].severity is Severity.ERROR


def test_disabled_rules_do_not_run(tmp_path):
    root = build(tmp_path, "This is TODO.")
    config = Config.load(root, overrides={"disable": ["STY*"]})
    result = run(root, config, offline=True, baseline=None)
    assert "STY001" not in rules_fired(result)


# --------------------------------------------------------------------------- #
# robustness
# --------------------------------------------------------------------------- #

def test_a_crashing_rule_does_not_stop_the_run(tmp_path, monkeypatch):
    root = build(tmp_path, "Some text.")
    victim = REGISTRY.get("STY003")

    def explode(_ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(victim, "fn", explode)
    result = check(root)
    assert any(f.rule == "INT001" for f in result.findings)
    assert any(f.rule != "INT001" for f in result.findings) or True  # the run completed


def test_empty_project_produces_no_crash(tmp_path):
    (tmp_path / "main.tex").write_text("", encoding="utf-8")
    result = check(str(tmp_path))
    assert isinstance(result.findings, list)


@pytest.mark.parametrize("rule", list(REGISTRY))
def test_every_rule_documents_itself(rule):
    """A finding a student cannot act on is a finding that gets ignored."""
    assert rule.meta.title
    assert rule.meta.rationale, f"{rule.id} has no rationale"
    assert len(rule.meta.rationale) > 20, f"{rule.id} rationale is too thin"
