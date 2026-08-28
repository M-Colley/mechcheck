"""The documentation must not contain shell damage.

Writing files through shell heredocs repeatedly turned LaTeX command names into
control characters -- ``\\ref`` into a carriage return, ``\\autoref`` into a bell
-- and the damage is invisible when reading the rendered Markdown. The fixtures
have had this guard for a while; the docs, which are what people actually read,
had not.
"""

from __future__ import annotations

import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))
              + glob.glob(os.path.join(ROOT, "*.md")))

#: A LaTeX command whose backslash was eaten leaves a recognisable stump.
STUMPS = re.compile(r"(?<![\\\w])(ef\{|utoref|egin\{|nd\{document|abel\{|ite\{[a-z])")


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT)


def test_there_are_docs():
    assert DOCS


@pytest.mark.parametrize("path", DOCS, ids=rel)
def test_no_control_characters(path):
    data = open(path, "rb").read()
    bad = sorted({b for b in data if b < 9 or 13 < b < 32})
    assert not bad, f"{rel(path)} contains control bytes {bad}"


@pytest.mark.parametrize("path", DOCS, ids=rel)
def test_no_decapitated_latex_commands(path):
    text = open(path, encoding="utf-8").read()
    hits = [m.group(0) for m in STUMPS.finditer(text)]
    assert not hits, f"{rel(path)} looks like it lost a backslash: {hits[:5]}"


@pytest.mark.parametrize("path", DOCS, ids=rel)
def test_is_valid_utf8(path):
    open(path, "rb").read().decode("utf-8")
