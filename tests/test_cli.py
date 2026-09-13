"""The command line, as a user meets it.

Each test here pins something that was broken in a way the rule tests could
not see: a hint that named a flag which did not exist, an entry point that
was missing, and a generated workflow that installed from a package index the
tool is not on.
"""

from __future__ import annotations

import os
import subprocess
import sys

import mechcheck.rules  # noqa: F401
from mechcheck.cli import main

BS = chr(92)
NL = chr(10)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(tmp_path, body: str) -> str:
    doc = (BS + "documentclass{article}" + NL + BS + "begin{document}" + NL
           + body + NL + BS + "end{document}" + NL)
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline=NL)
    return str(tmp_path)


def test_show_skipped_lists_the_rules_that_did_not_run(tmp_path, capsys):
    root = build(tmp_path, "Plain text without problems.")
    code = main(["check", root, "--offline", "--show-skipped", "--fail-on", "never", "--no-baseline"])
    out = capsys.readouterr().out
    assert code == 0
    assert "BIO001" in out and "network" in out
    assert "rules --skipped" not in out       # the flag this used to advertise never existed


def test_the_hint_names_a_flag_that_exists(tmp_path, capsys):
    root = build(tmp_path, "Plain text without problems.")
    main(["check", root, "--offline", "--fail-on", "never", "--no-baseline"])
    out = capsys.readouterr().out
    assert "--show-skipped" in out


def test_python_dash_m_runs_the_command_line():
    proc = subprocess.run([sys.executable, "-m", "mechcheck", "--help"],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0
    assert "check" in proc.stdout


def test_the_scaffolded_workflow_installs_from_the_repository():
    from mechcheck.scaffold import WORKFLOW

    assert "git+https://github.com/M-Colley/mechcheck" in WORKFLOW
    assert "pip install mechcheck" not in WORKFLOW    # not on PyPI: that line failed every CI run
