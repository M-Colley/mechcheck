"""The compile log, checked against a log a real Overleaf compile produced.

Synthetic logs only prove the regexes match what I imagined. This one is the
genuine article -- acmart 2026 v2.18 on Overleaf's TeX Live -- and it is here
because it exposed a gap: acmart raises its own accessibility warnings, and
nothing was surfacing them.
"""

from __future__ import annotations

import os

import pytest

import mechcheck.rules  # noqa: F401
from mechcheck.config import Config
from mechcheck.runner import run

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "overleaf-log")


def check(only=None, **overrides):
    config = Config.load(FIXTURE, overrides={
        "profile": "paper-anonymous", "venue": "autoui", **overrides})
    return run(FIXTURE, config, only=only, offline=True, baseline=None, build_dir=FIXTURE)


def rules_fired(result):
    return {f.rule for f in result.findings}


def test_the_fixture_is_a_real_overleaf_log():
    text = open(os.path.join(FIXTURE, "output.log"), encoding="utf-8", errors="replace").read()
    assert "This is pdfTeX" in text
    assert "acmart" in text


def test_undefined_reference_is_read_from_the_log():
    result = check(only=["LOG002"])
    assert "LOG002" in rules_fired(result)
    assert "sec:nowhere" in result.findings[0].message


def test_page_count_comes_from_the_log_when_there_is_no_pdf():
    """"Output written on output.pdf (1 page" is the only source here."""
    result = check(only=["MET002"])
    assert "MET002" in rules_fired(result)
    assert "1 pages" in result.findings[0].message


def test_no_spurious_findings_from_a_clean_compile():
    """The document compiled; nothing may claim otherwise."""
    result = check(only=["LOG001", "LOG003", "LOG004", "LOG005", "LOG006", "LOG007"])
    assert not result.findings, [f.message for f in result.findings]


def test_class_warnings_defer_to_the_source_rule_that_covers_them():
    """acmart warns about missing descriptions; ACC001 says it better."""
    result = check(only=["LOG009", "ACC001"])
    assert "ACC001" in rules_fired(result)
    assert "LOG009" not in rules_fired(result)


def test_class_warnings_are_surfaced_when_nothing_else_covers_them():
    result = check(only=["LOG009"], disable=["ACC001"])
    messages = [f.message for f in result.findings]
    assert any("acmart says" in m for m in messages), messages
    # one per location, not one per distinct wording
    lines = sorted(f.line for f in result.findings if f.line)
    assert lines == [57, 73], lines


def test_acmart_and_acc001_agree_on_which_figures_lack_a_description():
    r"""Two independent implementations, the same two figures.

    acmart reports at \end{figure}, ACC001 at \begin{figure}, so the line
    numbers differ by the height of the environment -- but they must be the
    same floats.
    """
    source = check(only=["ACC001"])
    from_class = check(only=["LOG009"], disable=["ACC001"])
    assert len(source.findings) == 2
    class_lines = sorted(f.line for f in from_class.findings if f.line)
    source_lines = sorted(f.line for f in source.findings)
    assert len(class_lines) == len(source_lines) == 2
    assert all(c > s for c, s in zip(class_lines, source_lines))
