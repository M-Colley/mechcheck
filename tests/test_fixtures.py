"""Fixtures must be byte-exact.

A shell heredoc silently turned ``\begin`` into a backspace character while
these fixtures were being written, which made one of them parse as a document
with no \begin{document} at all. The checker was fine; the fixture was not.
Control characters in a .tex fixture are always a mistake, so assert it.
"""

from __future__ import annotations

import glob
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SOURCES = sorted(glob.glob(os.path.join(FIXTURES, "**", "*.tex"), recursive=True)
                 + glob.glob(os.path.join(FIXTURES, "**", "*.bib"), recursive=True))


def test_there_are_fixtures():
    assert SOURCES, "no fixture sources found"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: os.path.relpath(p, FIXTURES))
def test_fixture_has_no_control_characters(path):
    data = open(path, "rb").read()
    bad = sorted({b for b in data if b < 9 or 13 < b < 32})
    assert not bad, f"{path} contains control bytes {bad} - it was mangled when written"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: os.path.relpath(p, FIXTURES))
def test_fixture_is_valid_utf8(path):
    open(path, "rb").read().decode("utf-8")
