"""One systematic habit must not bury everything else.

A generated 27,000-word thesis produced 1,708 findings, a single rule
accounting for 1,062 of them. Nobody reads that; they close it, and the twelve
findings that mattered go with the rest. So each rule shows at most a handful
and counts the remainder -- while the headline keeps telling the truth about
how many problems there actually are.
"""

from __future__ import annotations

import pytest

import mechcheck.rules  # noqa: F401
from mechcheck import report as reporters
from mechcheck.config import Config
from mechcheck.runner import run

BS = chr(92)


def build(tmp_path, body: str) -> str:
    doc = (BS + "documentclass{article}\n"
           + BS + "begin{document}\n" + body + "\n"
           + BS + "end{document}\n")
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline="\n")
    return str(tmp_path)


def check(root: str, only=None, **overrides):
    config = Config.load(root, overrides=overrides)
    return run(root, config, only=only, offline=True, baseline=None)


def repeated_words(tmp_path, n: int = 25) -> str:
    body = "\n".join(f"This is is repeated line number {i} here." for i in range(n))
    return build(tmp_path, body)


def test_findings_are_capped_per_rule(tmp_path):
    result = check(repeated_words(tmp_path), only=["STY003"])
    assert len(result.findings) == 10
    assert len(result.truncated) == 15


def test_the_headline_count_still_tells_the_truth(tmp_path):
    """A shortened list must not shrink the number of problems."""
    result = check(repeated_words(tmp_path), only=["STY003"])
    assert result.counts()["warn"] == 25


def test_truncated_findings_are_counted_per_rule(tmp_path):
    result = check(repeated_words(tmp_path), only=["STY003"])
    assert result.truncated_by_rule() == {"STY003": 15}


def test_the_cap_can_be_turned_off(tmp_path):
    result = check(repeated_words(tmp_path), only=["STY003"], max_per_rule=0)
    assert len(result.findings) == 25
    assert not result.truncated


def test_a_custom_cap_is_honoured(tmp_path):
    result = check(repeated_words(tmp_path), only=["STY003"], max_per_rule=3)
    assert len(result.findings) == 3
    assert len(result.truncated) == 22


def test_capping_never_hides_a_failure(tmp_path):
    """If every error sits past the cap, the run must still fail."""
    body = "\n".join(f"Line {i} is TODO." for i in range(25))
    result = check(build(tmp_path, body), only=["STY001"])
    assert len(result.findings) == 10
    assert result.truncated
    assert result.should_fail()


def test_the_text_report_says_what_it_held_back(tmp_path):
    text = reporters.render_text(check(repeated_words(tmp_path), only=["STY003"]), color=False)
    assert "and 15 more STY003" in text
    assert "15 not listed" in text


def test_the_markdown_report_lists_repeats_once(tmp_path):
    md = reporters.render_markdown(check(repeated_words(tmp_path), only=["STY003"]))
    assert "Repeated findings, listed once each" in md
    assert "`STY003` +15" in md


def test_markdown_still_reports_an_empty_run_correctly(tmp_path):
    """The held-back note must not displace the nothing-found message."""
    md = reporters.render_markdown(check(build(tmp_path, "Perfectly ordinary text."),
                                         only=["STY003"]))
    assert "No mechanical issues found" in md


def test_the_cap_keeps_the_most_severe_first(tmp_path):
    """Sorting runs before capping, so what survives is what matters most."""
    body = ("\n".join(f"Line {i} is is repeated." for i in range(20))
            + "\nA single TODO marker.")
    result = check(build(tmp_path, body), only=["STY001", "STY003"])
    assert any(f.rule == "STY001" for f in result.findings), "the error was capped away"


def test_json_output_carries_the_held_back_findings(tmp_path):
    import json

    payload = json.loads(reporters.render_json(check(repeated_words(tmp_path), only=["STY003"])))
    assert len(payload["findings"]) == 10
    assert len(payload["truncated"]) == 15
    assert payload["counts"]["warn"] == 25
