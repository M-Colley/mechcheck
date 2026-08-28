"""The self-test document, asserted from the Python side.

`latex/overleaf-selftest.tex` is what a person pastes into Overleaf to confirm
the whole chain works, so the findings it produces are a published contract.
The identical list is asserted in browser/test-engine.mjs: if the two
implementations ever disagree, one of these two suites fails, which is the
only way to catch drift between them.
"""

from __future__ import annotations

import collections
import os

import pytest

import mechcheck.rules  # noqa: F401
from mechcheck.config import Config
from mechcheck.runner import run

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "selftest")

EXPECTED = {
    "ABB001": 1, "ACC001": 2, "ACC004": 1, "ANON001": 1, "ANON003": 1, "ANON004": 2,
    "ANON005": 1, "BIB006": 1, "BIB008": 1, "BIB009": 1, "FIG003": 1, "MET003": 1,
    "MET004": 1, "POL001": 1, "POL002": 1, "POL003": 1, "POL004": 1, "POL005": 1,
    "POL006": 1, "POL007": 1, "REF001": 1, "REF008": 3, "REF009": 2, "STY001": 1,
    "STY003": 1, "STY005": 1, "STY007": 1, "VEN002": 2, "VEN003": 1, "VEN004": 2,
}


@pytest.fixture(scope="module")
def counts():
    config = Config.load(FIXTURE, overrides={
        "profile": "paper-anonymous", "stage": "submission", "venue": "autoui"})
    result = run(FIXTURE, config, offline=True, baseline=None)
    return collections.Counter(f.rule for f in result.findings)


@pytest.mark.parametrize("rule_id,expected", sorted(EXPECTED.items()))
def test_expected_rule_fires_the_documented_number_of_times(counts, rule_id, expected):
    assert counts.get(rule_id, 0) == expected


def test_nothing_unexpected_fires(counts):
    unexpected = {r: n for r, n in counts.items() if r not in EXPECTED}
    assert not unexpected, f"undocumented findings: {unexpected}"


def test_total_matches_the_documented_figure(counts):
    assert sum(counts.values()) == 37
