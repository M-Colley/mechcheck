"""Recomputing what the statistics say, and comparing it to what was written.

A reported test has two numbers that have to agree: the test statistic with
its degrees of freedom, and the p-value. Either can be mistyped, and a
transposed digit in a p-value is invisible to every reader -- there is no way
to notice it except by doing the arithmetic again. That makes this the most
mechanical check in the whole tool: no judgement, no threshold, no opinion
about the research, just whether two numbers in the same sentence describe
the same result.

Two decisions keep it from crying wolf, and both matter more than the
arithmetic:

**Rounding is taken seriously.** "t(48) = 2.13" was rounded from somewhere in
[2.125, 2.135), which gives a range of possible p-values rather than one.
The reported p was rounded too. A finding is raised only when those two
ranges do not overlap at all, so a correctly reported test can never be
flagged for being rounded.

**A one-tailed test is not an error.** Papers often report a one-tailed p
without saying so. Where halving the two-tailed p would make the numbers
agree, this says nothing: it cannot tell a one-tailed test from a mistake,
and guessing wrong would accuse somebody of an error they did not make.

The remaining findings are arithmetic. `mechcheck explain STA001` says so.
"""

from __future__ import annotations

import math
import re

from mechcheck.model import Category, Severity, rule
from mechcheck.stats import TESTS, rounding_interval

#: One reported test: a statistic, its degrees of freedom, and the p beside
#: it. The gap between them may hold an effect size ("eta^2 = .17, ") but may
#: not cross into the next sentence, which is what the lookahead excludes.
_TEST_REPORT = re.compile(r"""
    (?<![A-Za-z\\])
    (?P<kind>
        \\?chi\s*\^?\s*\{?\s*2\s*\}?
      | \u03c7\s*\^?\s*\{?\s*[2\u00b2]\s*\}?
      | [tFrz](?![A-Za-z])
    )
    \s*
    (?:
      \(\s* (?P<df1>\d+(?:\.\d+)?) \s*
      (?: , \s* (?: [Nn]\s*=\s*[\d,]+ | (?P<df2>\d+(?:\.\d+)?) ) \s* )?
      \)
    )?
    \s* = \s*
    (?P<value>[-\u2212+]?\d*\.\d+|[-\u2212+]?\d+)
    (?P<gap>(?:(?!\.\s+[A-Z])[^\n]){0,60}?)
    (?<![A-Za-z])p\s*(?P<op>[<>=])\s*(?P<p>\d*\.\d+|\d+)
""", re.VERBOSE)

#: Any p-value at all, for the impossible-value check.
_ANY_P = re.compile(r"(?<![A-Za-z])p\s*(?P<op>[<>=])\s*(?P<p>\d*\.\d+|\d+)")

#: How each statistic is written back in a finding.
_DISPLAY = {"t": "t", "F": "F", "r": "r", "z": "z", "chi2": "chi²"}


def _normalise_kind(text: str) -> str:
    """Which test this is. Case is meaning here: F and t are not the same."""
    cleaned = text.strip().replace(" ", "")
    if cleaned in ("t", "F", "r", "z"):
        return cleaned
    return "chi2"


def _describe(kind: str, dfs: list, value: str) -> str:
    """The test as this finding will name it, free of the source's markup."""
    numbers = ", ".join(f"{d:g}" for d in dfs)
    head = _DISPLAY.get(kind, kind)
    return f"{head}({numbers}) = {value}" if dfs else f"{head} = {value}"


def _format_p(p: float) -> str:
    if p < 0.0001:
        return f"{p:.2e}"
    return f"{p:.4f}".rstrip("0").rstrip(".")


def _p_range(kind: str, value_text: str, dfs: list):
    """Every p-value consistent with the statistic as it was written."""
    needed, compute = TESTS[kind]
    if len(dfs) < needed:
        return None
    low, high = rounding_interval(value_text)
    points = [low, high]
    if low < 0.0 < high:
        points.append(0.0)          # |statistic| can reach zero in the interval
    values = []
    for point in points:
        try:
            p = compute(point, dfs)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        if p != p or p < 0.0 or p > 1.0:     # NaN or out of range: say nothing
            return None
        values.append(p)
    return min(values), max(values)


def _agrees(p_low: float, p_high: float, op: str, reported: str) -> bool:
    if op == "=":
        low, high = rounding_interval(reported)
        return not (p_high < low or p_low > high)
    value = float(reported)
    if op == "<":
        return p_low < value
    return p_high > value


def _decision_differs(p_low: float, p_high: float, op: str, reported: str,
                      alpha: float = 0.05) -> bool:
    """Do the computed and reported p-values fall on opposite sides of alpha?"""
    computed_significant = p_high < alpha
    computed_not = p_low > alpha
    try:
        value = float(reported)
    except ValueError:
        return False
    claimed_significant = value < alpha if op in ("=", "<") else False
    claimed_not = value > alpha if op in ("=", ">") else False
    return (computed_significant and claimed_not) or (computed_not and claimed_significant)


@rule("STA001", "Reported p-value does not match the test statistic", Category.STATS,
      Severity.WARN,
      rationale="A transposed digit in a p-value cannot be seen by reading; the only way to notice is to compute the p-value again from the statistic and its degrees of freedom. Where the two disagree, one of the numbers in that sentence is wrong.",
      fix="Recompute the p-value from the test statistic, and correct whichever number is wrong. If the test was one-tailed, say so in the text.")
def inconsistent_p_value(ctx):
    alpha = float(ctx.opt("STA001", "alpha", 0.05) or 0.05)
    for m in _TEST_REPORT.finditer(ctx.project.text):
        kind = _normalise_kind(m.group("kind"))
        if kind not in TESTS:
            continue
        dfs = [float(d) for d in (m.group("df1"), m.group("df2")) if d]
        computed = _p_range(kind, m.group("value"), dfs)
        if computed is None:
            continue                 # no degrees of freedom: POL006 says that
        p_low, p_high = computed
        op, reported = m.group("op"), m.group("p")
        if _agrees(p_low, p_high, op, reported):
            continue
        # A one-tailed test halves the two-tailed p, and papers do not always
        # say which they ran. Where that would reconcile the two, say nothing.
        if kind in ("t", "r", "z") and _agrees(p_low / 2, p_high / 2, op, reported):
            continue
        shown = _describe(kind, dfs, m.group("value"))
        midpoint = (p_low + p_high) / 2
        message = (f"{shown} gives p = {_format_p(midpoint)}, "
                   f"but the paper reports p {op} {reported}")
        if _decision_differs(p_low, p_high, op, reported, alpha):
            message += f", which changes whether the result is significant at {alpha:g}"
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STA001", message,
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          data={"test": kind, "df": dfs, "statistic": m.group("value"),
                                "reported_p": reported, "computed_p": midpoint})


@rule("STA002", "A p-value that cannot exist", Category.STATS, Severity.WARN,
      rationale="A p-value is a probability: it is never exactly zero, never negative, and never above one. 'p = .000' is a rounded value printed by software, and it hides how small the p-value actually was.",
      fix="Write p < .001 for a very small p-value, and check the others against your output.")
def impossible_p_value(ctx):
    for m in _ANY_P.finditer(ctx.project.text):
        op, text = m.group("op"), m.group("p")
        try:
            value = float(text)
        except ValueError:
            continue
        if op == "=" and value == 0.0:
            reason = "no p-value is exactly zero; this is a rounded printout"
            fix = "Write p < .001 instead."
        elif value > 1.0:
            reason = "a p-value cannot be greater than 1"
            fix = "Check the number against your output."
        else:
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STA002", f"p {op} {text}: {reason}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=fix, data={"reported_p": text})
