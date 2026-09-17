"""No control characters anywhere in the sources.

Writing files through this toolchain has repeatedly eaten a level of
escaping: ``\\begin`` became a backspace byte in a fixture, ``\\autoref`` a
bell character in the docs, and a ``\\u0000`` written into the browser engine
arrived as four literal NUL bytes. Each time the damage was invisible in the
rendered output and the code still ran, which is exactly why it survived.

The fixtures and the Markdown have had this guard for a while. The code had
not, and the code is where it happened most recently.
"""

from __future__ import annotations

import glob
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = ("mechcheck/**/*.py", "mechcheck/**/*.yaml", "tests/**/*.py",
            "browser/*.html", "browser/*.mjs", "extension/*.js", "extension/*.html",
            "extension/*.json", "latex/*.sty", "latex/*.tex", "latex/*.sh",
            "scripts/*.py", ".github/workflows/*.yml")

SOURCES = sorted({path for pattern in PATTERNS
                  for path in glob.glob(os.path.join(ROOT, pattern), recursive=True)
                  if "test-harness.built.html" not in path})


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def test_there_are_sources():
    assert len(SOURCES) > 30


@pytest.mark.parametrize("path", SOURCES, ids=rel)
def test_no_control_characters(path):
    data = open(path, "rb").read()
    bad = sorted({b for b in data if b < 9 or 13 < b < 32})
    assert not bad, (f"{rel(path)} contains control bytes {bad} -- something ate an "
                     f"escaping level while writing it")


@pytest.mark.parametrize("path", SOURCES, ids=rel)
def test_is_valid_utf8(path):
    open(path, "rb").read().decode("utf-8")
