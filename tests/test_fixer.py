"""Automatic fixes, and the limits on them.

A rule earns a fix only when there is exactly one right answer. The tests that
matter most here are the negative ones: that a rule needing judgement carries
no fix, and that applying every fix leaves the project no worse than it was.
"""

from __future__ import annotations

import mechcheck.rules  # noqa: F401
from mechcheck import fixer
from mechcheck.config import Config
from mechcheck.runner import run

BS = chr(92)


def build(tmp_path, body: str, cls: str = "acmart") -> str:
    doc = (BS + "documentclass{" + cls + "}\n"
           + BS + "begin{document}\n" + body + "\n" + BS + "end{document}\n")
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline="\n")
    return str(tmp_path)


def do_fix(root, **overrides):
    config = Config.load(root, overrides={"max_per_rule": 0, **overrides})
    return fixer.fix(root, config, run, offline=True)


def body_of(root) -> str:
    import os

    with open(os.path.join(root, "main.tex"), encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# the fixes themselves
# --------------------------------------------------------------------------- #

def test_repeated_word_is_deleted(tmp_path):
    root = build(tmp_path, "This is is a problem in the text.")
    do_fix(root)
    # Careful: "This is a problem" *contains* the substring "is is" (the end of
    # "This" plus " is"), so assert on the corrected sentence, not a substring.
    assert "This is a problem in the text." in body_of(root)


def test_abbreviation_reintroduction_is_collapsed(tmp_path):
    body = ("The Automated Driving System (ADS) is new. The ADS works well.\n"
            "Later the Automated Driving System (ADS) appears again here.")
    root = build(tmp_path, body)
    do_fix(root)
    text = body_of(root)
    assert text.count("Automated Driving System (ADS)") == 1
    assert "Later the ADS appears again here." in text


def test_prefixed_reference_becomes_autoref(tmp_path):
    root = build(tmp_path, "As shown in Figure~" + BS + "ref{fig:a}, it holds.")
    do_fix(root)
    assert BS + "autoref{fig:a}" in body_of(root)
    assert "Figure~" not in body_of(root)


def test_name_before_cite_becomes_citet(tmp_path):
    root = build(tmp_path, "Colley et al.~" + BS + "cite{a} showed this.")
    do_fix(root)
    assert BS + "citet{a}" in body_of(root)


def test_space_before_punctuation_is_closed_up(tmp_path):
    root = build(tmp_path, "A sentence with a space before , this comma.")
    do_fix(root)
    assert " ," not in body_of(root)


def test_numeric_range_gets_an_en_dash(tmp_path):
    root = build(tmp_path, "We recruited 10-20 participants for the study.")
    do_fix(root)
    assert "10--20" in body_of(root)


# --------------------------------------------------------------------------- #
# the limits
# --------------------------------------------------------------------------- #

def test_alt_text_is_never_auto_fixed(tmp_path):
    """No machine can write a figure description; ACC001 must carry no edit."""
    body = (BS + "begin{figure}" + BS + "caption{A}" + BS + "label{fig:a}"
            + BS + "end{figure}\nSee " + BS + "autoref{fig:a}.")
    root = build(tmp_path, body)
    config = Config.load(root, overrides={"max_per_rule": 0})
    result = run(root, config, offline=True, baseline=None)
    acc = [f for f in result.findings if f.rule.startswith("ACC")]
    assert acc, "expected an accessibility finding to test against"
    assert all(f.edit is None for f in acc)


def test_a_lone_surname_is_not_rewritten(tmp_path):
    """The rule does not fire for it, so the text must be untouched."""
    root = build(tmp_path, "Bazilinskyy~" + BS + "cite{a} measured it.")
    before = body_of(root)
    do_fix(root)
    assert body_of(root) == before


def test_nothing_is_written_on_a_dry_run(tmp_path):
    root = build(tmp_path, "This is is a problem in the text.")
    before = body_of(root)
    config = Config.load(root, overrides={"max_per_rule": 0})
    report = fixer.fix(root, config, run, offline=True, dry_run=True)
    assert report.applied
    assert body_of(root) == before


def test_the_result_is_verified_afterwards(tmp_path):
    """Fixing is only safe because the project is re-checked."""
    body = ("As shown in Figure~" + BS + "ref{fig:a} and Table~" + BS + "ref{tab:b}.\n"
            "This is is repeated.")
    report = do_fix(build(tmp_path, body))
    assert report.ok, report.new_findings
    assert report.resolved()


def test_fixing_a_clean_document_changes_nothing(tmp_path):
    root = build(tmp_path, "A perfectly ordinary sentence with nothing wrong.")
    before = body_of(root)
    report = do_fix(root)
    assert not report.applied
    assert body_of(root) == before


def test_overlapping_fixes_are_refused_not_mangled(tmp_path):
    """Two edits over the same span: apply one, skip the other, never both."""
    from mechcheck.fixer import FixReport, apply_to_text
    from mechcheck.model import Edit, Finding

    text = "hello world"
    a = Finding(rule="A", message="", edit=Edit(file="f", start=0, end=5, replacement="HI"))
    b = Finding(rule="B", message="", edit=Edit(file="f", start=3, end=8, replacement="X"))
    report = FixReport()
    # right-to-left, as the fixer applies them
    out = apply_to_text(text, [(b, b.edit), (a, a.edit)], report, "f")
    # Edits are applied right-to-left, so the later span wins and the one that
    # would have overlapped it is refused. Which one wins matters less than
    # that exactly one does, and that the text is never spliced twice.
    assert out == "helXrld"
    assert len(report.applied) == 1
    assert len(report.skipped) == 1
    assert "overlaps" in report.skipped[0][2]


def test_line_endings_survive(tmp_path):
    """A Windows file must not come back with its line endings changed."""
    import os

    doc = (BS + "documentclass{article}\r\n" + BS + "begin{document}\r\n"
           + "This is is a problem.\r\n" + BS + "end{document}\r\n")
    path = os.path.join(str(tmp_path), "main.tex")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(doc)
    do_fix(str(tmp_path))
    with open(path, "rb") as fh:
        raw = fh.read()
    assert b"\r\n" in raw
    assert b"This is a problem." in raw
