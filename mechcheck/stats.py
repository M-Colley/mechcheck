"""The distribution functions needed to recompute a reported p-value.

Standard library only, like the rest of this package: ``pip install
mechcheck`` has to work on a bare runner, and a checker that needs SciPy to
read a LaTeX file is a checker nobody installs. What is here is the classic
pair of series-and-continued-fraction expansions -- the regularised
incomplete beta and the regularised incomplete gamma -- which between them
give the t, F, chi-square and normal tails.

The browser engine carries the same functions, and both are checked against
the same table of known values, so the two never disagree about whether a
reported p-value is possible.

Accuracy is far beyond what the task needs. A p-value is reported to three
decimals at best, and every comparison here is made between *intervals* that
account for that rounding, so an error in the twelfth digit cannot change a
verdict.
"""

from __future__ import annotations

import math

_TINY = 1e-300
_EPS = 3e-16
_MAX_ITERATIONS = 500


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta, by Lentz's method."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2 * m
        # even step
        num = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + num / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        h *= d * c
        # odd step
        num = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + num * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + num / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta, I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                + a * math.log(x) + b * math.log1p(-x))
    front = math.exp(ln_front)
    # The continued fraction converges quickly only on one side; the identity
    # I_x(a,b) = 1 - I_(1-x)(b,a) covers the other, and the front factor is
    # symmetric under that swap.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _gamma_series(a: float, x: float) -> float:
    """Lower regularised incomplete gamma P(a, x), by its series."""
    term = total = 1.0 / a
    ap = a
    for _ in range(_MAX_ITERATIONS):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_cf(a: float, x: float) -> float:
    """Upper regularised incomplete gamma Q(a, x), by continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _TINY
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITERATIONS):
        num = -i * (i - a)
        b += 2.0
        d = num * d + b
        if abs(d) < _TINY:
            d = _TINY
        c = b + num / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammainc_upper(a: float, x: float) -> float:
    """Regularised upper incomplete gamma, Q(a, x)."""
    if x <= 0.0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gamma_series(a, x)
    return _gamma_cf(a, x)


# --------------------------------------------------------------------------- #
# the four tails a paper actually reports
# --------------------------------------------------------------------------- #

def p_from_t(t: float, df: float) -> float:
    """Two-tailed p for Student's t."""
    if df <= 0:
        return float("nan")
    t = abs(t)
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def p_from_f(f: float, df1: float, df2: float) -> float:
    """Upper-tail p for the F ratio. F tests are one-tailed by construction."""
    if f < 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    return betainc(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f))


def p_from_chi2(x: float, df: float) -> float:
    """Upper-tail p for chi-square."""
    if x < 0 or df <= 0:
        return float("nan")
    return gammainc_upper(df / 2.0, x / 2.0)


def p_from_z(z: float) -> float:
    """Two-tailed p for the standard normal.

    Computed through the same incomplete gamma as chi-square rather than
    through ``erfc``: z squared is chi-square on one degree of freedom, and
    sharing the path keeps this engine and the browser's bit-for-bit alike.
    """
    return gammainc_upper(0.5, z * z / 2.0)


def p_from_r(r: float, df: float) -> float:
    """Two-tailed p for a correlation, through its t equivalent."""
    if df <= 0 or abs(r) >= 1.0:
        return float("nan")
    return p_from_t(r * math.sqrt(df / (1.0 - r * r)), df)


#: How to recompute each statistic a paper reports, and how many degrees of
#: freedom it needs before the recomputation is possible at all.
TESTS = {
    "t": (1, lambda v, df: p_from_t(v, df[0])),
    "F": (2, lambda v, df: p_from_f(v, df[0], df[1])),
    "r": (1, lambda v, df: p_from_r(v, df[0])),
    "chi2": (1, lambda v, df: p_from_chi2(v, df[0])),
    "z": (0, lambda v, df: p_from_z(v)),
}


def rounding_interval(text: str) -> tuple:
    """The range a number could have come from, given how it was written.

    "2.13" was rounded from somewhere in [2.125, 2.135), and a comparison
    that ignores that reports half of all correctly-reported tests as wrong.
    """
    cleaned = text.strip().lstrip("+").replace("−", "-")
    decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
    half = 0.5 * (10.0 ** -decimals)
    value = float(cleaned)
    return (value - half, value + half)
