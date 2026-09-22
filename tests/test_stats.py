"""Recomputing a reported p-value, and the arithmetic underneath it.

The distribution functions are checked against a method that shares no code
with them -- numerical integration of the density, and the standard library's
own normal distribution -- because a table of constants copied from somewhere
only proves the constants were copied.

The rule itself is checked mostly in the negative. A correctly reported test
must never be flagged, whatever rounding it used, and a one-tailed p must
never be flagged either, because this cannot tell one from a mistake.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pytest

import mechcheck.rules  # noqa: F401
from mechcheck.config import Config
from mechcheck.runner import run
from mechcheck.stats import (p_from_chi2, p_from_f, p_from_r, p_from_t, p_from_z,
                             rounding_interval)

BS = chr(92)
NL = chr(10)


# --------------------------------------------------------------------------- #
# the arithmetic, against an independent method
# --------------------------------------------------------------------------- #

def _simpson(f, a: float, b: float, n: int = 20000) -> float:
    h = (b - a) / n
    total = f(a) + f(b)
    for i in range(1, n):
        total += f(a + i * h) * (4 if i % 2 else 2)
    return total * h / 3


def _tail(density, start: float, n: int = 20000) -> float:
    """Integrate a density from ``start`` to infinity.

    Through x = start + tan(theta), so the whole tail is covered rather than
    truncated: a t density on few degrees of freedom still carries about 1e-5
    of its mass beyond start + 60, which is larger than what is being checked.
    """
    edge = math.pi / 2

    def transformed(theta):
        if theta >= edge - 1e-9:
            return 0.0
        return density(start + math.tan(theta)) / math.cos(theta) ** 2

    return _simpson(transformed, 0.0, edge - 1e-9, n)


def _t_tail_by_integration(t: float, df: float) -> float:
    scale = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    return 2 * _tail(lambda x: scale * (1 + x * x / df) ** (-(df + 1) / 2), t)


def _f_tail_by_integration(x: float, d1: float, d2: float) -> float:
    ln_scale = ((d1 / 2) * math.log(d1) + (d2 / 2) * math.log(d2)
                + math.lgamma((d1 + d2) / 2) - math.lgamma(d1 / 2) - math.lgamma(d2 / 2))

    def density(u):
        if u <= 0:
            return 0.0
        return math.exp(ln_scale + (d1 / 2 - 1) * math.log(u)
                        - ((d1 + d2) / 2) * math.log(d2 + d1 * u))

    return _tail(density, x)


@pytest.mark.parametrize("t,df", [(2.13, 48), (2.10, 18), (1.0, 9), (3.5, 200), (0.5, 3)])
def test_the_t_tail_matches_an_independent_integral(t, df):
    assert p_from_t(t, df) == pytest.approx(_t_tail_by_integration(t, df), abs=1e-7)


@pytest.mark.parametrize("f,d1,d2", [(4.71, 2, 46), (3.94, 1, 100), (10.0, 3, 20)])
def test_the_f_tail_matches_an_independent_integral(f, d1, d2):
    assert p_from_f(f, d1, d2) == pytest.approx(_f_tail_by_integration(f, d1, d2), abs=1e-7)


@pytest.mark.parametrize("z", [0.5, 1.0, 1.96, 2.576, 4.0])
def test_the_normal_tail_matches_the_standard_library(z):
    assert p_from_z(z) == pytest.approx(2 * (1 - NormalDist().cdf(z)), abs=1e-12)


def test_chi_square_on_one_degree_of_freedom_is_the_squared_normal():
    for x in (0.5, 3.84, 6.63):
        assert p_from_chi2(x, 1) == pytest.approx(p_from_z(math.sqrt(x)), abs=1e-12)


def test_a_correlation_goes_through_its_t_equivalent():
    assert p_from_r(0.42, 38) == pytest.approx(p_from_t(0.42 * math.sqrt(38 / (1 - 0.42 ** 2)), 38))


def test_the_tails_run_the_right_way():
    assert p_from_t(0.0, 10) == pytest.approx(1.0)
    assert p_from_t(50.0, 10) < 1e-10
    assert p_from_chi2(0.0, 3) == pytest.approx(1.0)
    assert p_from_f(0.0, 2, 10) == pytest.approx(1.0)


#: The same table browser/test-engine.mjs pins. The two engines share no
#: code, so agreeing on these to the last few bits is what says their
#: answers about a paper will agree too.
SHARED_WITH_THE_BROWSER = [
    ("t", lambda: p_from_t(2.13, 48), 0.038325242106873),
    ("t", lambda: p_from_t(1.0, 9), 0.343436396137915),
    ("F", lambda: p_from_f(4.71, 2, 46), 0.013775270491189),
    ("chi2", lambda: p_from_chi2(3.84, 1), 0.050043521248705),
    ("z", lambda: p_from_z(1.96), 0.049995790296441),
    ("r", lambda: p_from_r(0.42, 38), 0.006973232419529),
]


@pytest.mark.parametrize("kind,compute,expected", SHARED_WITH_THE_BROWSER,
                         ids=[f"{k}-{e:.4g}" for k, _c, e in SHARED_WITH_THE_BROWSER])
def test_both_engines_agree_to_the_last_bits(kind, compute, expected):
    assert compute() == pytest.approx(expected, abs=1e-12)


def test_rounding_intervals_follow_the_digits_written():
    assert rounding_interval("2.13") == pytest.approx((2.125, 2.135))
    assert rounding_interval("2.130") == pytest.approx((2.1295, 2.1305))
    assert rounding_interval("5") == pytest.approx((4.5, 5.5))
    assert rounding_interval(".05") == pytest.approx((0.045, 0.055))


# --------------------------------------------------------------------------- #
# the rule
# --------------------------------------------------------------------------- #

def build(tmp_path, body: str) -> str:
    doc = (BS + "documentclass{article}" + NL + BS + "begin{document}" + NL
           + body + NL + BS + "end{document}" + NL)
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8", newline=NL)
    return str(tmp_path)


def check(tmp_path, body: str, only=("STA001", "STA002")):
    root = build(tmp_path, body)
    config = Config.load(root, overrides={"max_per_rule": 0, "profile": "paper", "venue": None})
    return run(root, config, only=list(only), offline=True, baseline=None)


def fired(result) -> set:
    return {f.rule for f in result.findings}


@pytest.mark.parametrize("body", [
    "The effect held, t(48) = 2.13, p = .038, d = 0.61.",
    "There was an effect, F(2, 46) = 4.71, p = .014.",
    "The test was significant, " + BS + "chi^2(1) = 3.84, p = .05.",
    "The difference held, z = 1.96, p = .05.",
    "They correlated, r(38) = .42, p = .007.",
    "It held, F(2, 46) = 4.71, eta^2 = .17, p = .014.",
    "Welch corrected, t(23.4) = 2.51, p = .019.",
    "It held, t(48) = 2.13, p < .05.",
    "Close to the line, t(18) = 2.10, p = .050.",
])
def test_a_correctly_reported_test_is_never_flagged(tmp_path, body):
    assert "STA001" not in fired(check(tmp_path, body))


@pytest.mark.parametrize("body,expected", [
    ("The effect held, t(48) = 2.13, p = .0038.", "0.0383"),
    ("There was an effect, F(2, 46) = 4.71, p = .14.", "0.0138"),
    ("The test was significant, " + BS + "chi^2(1) = 3.84, p = .001.", "0.05"),
    ("It held, t(48) = 1.02, p < .001.", "0.3128"),
])
def test_an_inconsistent_test_is_reported_with_the_right_answer(tmp_path, body, expected):
    result = check(tmp_path, body, only=["STA001"])
    assert "STA001" in fired(result)
    assert expected in result.findings[0].message


def test_the_finding_says_when_the_significance_decision_changes(tmp_path):
    result = check(tmp_path, "There was an effect, F(2, 46) = 4.71, p = .14.", only=["STA001"])
    assert "changes whether the result is significant" in result.findings[0].message


def test_a_consistent_test_that_does_not_cross_alpha_says_nothing_about_it(tmp_path):
    result = check(tmp_path, "It held, t(48) = 2.13, p = .0038.", only=["STA001"])
    assert "changes whether" not in result.findings[0].message


def test_a_one_tailed_p_is_not_called_an_error(tmp_path):
    """Half the two-tailed p. This cannot tell that from a mistake."""
    assert "STA001" not in fired(check(tmp_path, "One-tailed, t(48) = 2.13, p = .019."))


def test_an_f_test_gets_no_one_tailed_allowance(tmp_path):
    """F is one-tailed already, so halving it explains nothing."""
    result = check(tmp_path, "It held, F(2, 46) = 4.71, p = .0069.", only=["STA001"])
    assert "STA001" in fired(result)


def test_a_test_without_degrees_of_freedom_cannot_be_recomputed(tmp_path):
    """POL006 reports the missing df; this rule has nothing to work from."""
    assert "STA001" not in fired(check(tmp_path, "The effect held, t = 2.13, p = .0038."))


def test_two_numbers_in_different_sentences_are_not_one_test(tmp_path):
    body = "We used t(48) = 2.13. Separately, p = .9 described something else."
    assert "STA001" not in fired(check(tmp_path, body))


def test_statistics_inside_maths_are_still_read(tmp_path):
    """Half of all papers write their tests in maths mode."""
    assert "STA001" in fired(check(tmp_path, "The effect held, $t(48) = 2.13$, $p = .0038$."))


def test_a_chi_square_with_a_sample_size_in_the_parentheses(tmp_path):
    body = "The association held, " + BS + "chi^2(1, N = 100) = 3.84, p = .001."
    assert "STA001" in fired(check(tmp_path, body))


def test_ordinary_prose_with_letters_and_numbers_is_not_a_test(tmp_path):
    body = ("The room was 21 degrees. Table 2 lists the results, and figure 3 "
            "shows the trend over 48 trials.")
    assert not fired(check(tmp_path, body))


def test_an_impossible_p_value_is_reported(tmp_path):
    result = check(tmp_path, "It was significant, t(48) = 9.9, p = .000.", only=["STA002"])
    assert "STA002" in fired(result)
    assert "exactly zero" in result.findings[0].message


def test_a_p_value_above_one_is_reported(tmp_path):
    assert "STA002" in fired(check(tmp_path, "Reported oddly, p = 1.4 in that table.",
                                   only=["STA002"]))


@pytest.mark.parametrize("body", [
    "The result was clear, p < .001 throughout.",
    "It was not significant, p = .87 in that condition.",
    "Exactly at the boundary, p = 1 for the saturated model.",
])
def test_an_ordinary_p_value_is_not_impossible(tmp_path, body):
    assert "STA002" not in fired(check(tmp_path, body, only=["STA002"]))
