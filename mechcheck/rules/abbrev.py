"""Abbreviations and acronyms.

The rule everyone breaks: define once, at first use, then never again.  Finding
the second definition by eye means holding 60 pages in your head, which is
exactly why it survives into submitted theses.

Detection works on the pattern ``Long Form (LF)`` -- an expansion immediately
followed by its parenthesised initials -- plus bare all-caps tokens.  Anything
declared through the ``acronym``/``glossaries`` packages is handled by the
package itself and skipped, since those make the mistake impossible.
"""

from __future__ import annotations

import re
from collections import defaultdict

from mechcheck.model import Category, Severity, rule

#: Written out in full, these are never "abbreviations a reader must be taught".
COMMON = {
    "AI", "API", "CPU", "GPU", "CSV", "PDF", "HTML", "HTTP", "HTTPS", "URL", "USB",
    "RAM", "ROM", "OS", "PC", "ID", "IT", "UK", "USA", "US", "EU", "GDPR", "ISO",
    "IEEE", "ACM", "CHI", "DOI", "FAQ", "GPS", "LED", "PIN", "RGB", "SQL", "XML",
    "JSON", "YAML", "OK", "TV", "3D", "2D", "1D", "AM", "PM", "CI", "CD", "IRB",
    "ANOVA", "SD", "SE", "CI95", "RQ", "H1", "H2", "H3", "LLM", "ML", "DL", "NLP",
    # widely understood in HCI and computing writing
    "NASA", "HCI", "VR", "AR", "XR", "MR", "UI", "UX", "HMD", "GB", "MB",
    "TB", "KB", "HZ", "FPS", "SUS", "TLX", "IQR", "SPSS", "PDF", "DOI",
    # editing markers, reported by STY001 instead
    "TODO", "FIXME", "XXX", "TBD", "HACK", "NOTE",
}

#: Roman numerals, units and other all-caps sequences that are not acronyms.
_NOT_ACRONYM = re.compile(r"^(?:[IVXLCDM]+|[A-Z]|\d+[A-Z]*|[A-Z]{2}\d+)$")

_DEFINITION = re.compile(
    r"(?P<expansion>(?:[A-Z][\w\-]*|of|the|for|and|in|on|to|a|an)"
    r"(?:[ \-](?:[A-Za-z][\w\-]*|of|the|for|and|in|on|to|a|an)){0,7})"
    r"\s*\((?P<acronym>[A-Z][A-Za-z]{1,9}s?)\)")

_ACRONYM_USE = re.compile(r"(?<![\w\\])([A-Z]{2,9})(s|es)?(?![\w])")


def _managed_by_package(ctx) -> bool:
    packages = ctx.project.packages()
    return any(p in packages for p in ("acronym", "glossaries", "glossaries-extra",
                                       "acro", "nomencl", "abbrevs"))


def _ignored(ctx) -> set:
    extra = ctx.opt("ABB001", "ignore", []) or []
    extra += ctx.opt("ABB004", "ignore", []) or []
    return COMMON | {str(x).strip().upper() for x in extra}


def _definitions(ctx) -> dict:
    """Map acronym -> list of (acronym_at, expansion, start, end, as_written)."""
    cached = ctx.cache.get("abbrev_definitions")
    if cached is not None:
        return cached
    found = defaultdict(list)
    for m in _DEFINITION.finditer(ctx.project.prose):
        acronym = m.group("acronym").strip()
        expansion = " ".join(m.group("expansion").split())
        initials = "".join(w[0] for w in re.split(r"[ \-]", expansion) if w)
        plural = acronym.endswith("s") and acronym[:-1].isupper()
        core = acronym[:-1] if plural else acronym
        # Require the expansion to actually produce the acronym, allowing for
        # dropped articles ("Level of Automation (LoA)") and case differences.
        if not _initials_match(initials, core):
            continue
        # Keep only the words that actually produce the acronym. Without this,
        # "Later the Automated Driving System (ADS)" counts "Later the" as part
        # of the term -- and the auto-fix would delete those words.
        expansion, trimmed_by = _minimal_expansion(expansion, core)
        found[core.upper()].append(
            (m.start("acronym"), expansion, m.start() + trimmed_by, m.end(), acronym))
    ctx.cache["abbrev_definitions"] = found
    return found


def _minimal_expansion(expansion: str, acronym: str):
    """Shortest trailing run of words that still yields the acronym.

    Returns ``(expansion, characters_trimmed_from_the_front)`` so a caller can
    correct the span as well as the text.
    """
    words = expansion.split(" ")
    # Search from the shortest suffix upwards. Going the other way always
    # matches the whole string first -- the initials of "Later the Automated
    # Driving System" still contain A, D and S in order -- and nothing is
    # trimmed at all.
    for start in range(len(words) - 1, -1, -1):
        candidate = words[start:]
        initials = "".join(w[0] for w in " ".join(candidate).replace("-", " ").split() if w)
        if _initials_match(initials, acronym):
            trimmed = " ".join(candidate)
            return trimmed, len(expansion) - len(trimmed)
    return expansion, 0


def _initials_match(initials: str, acronym: str) -> bool:
    a = acronym.upper()
    i = initials.upper()
    if i == a:
        return True
    # allow skipped stop-words: LoA from "Level of Automation" gives LOA
    stripped = "".join(c for c in i if c.isalpha())
    if stripped == a:
        return True
    # subsequence: every acronym letter appears in order among the initials
    it = iter(stripped)
    return all(ch in it for ch in a) and len(a) >= 2


@rule("ABB001", "Abbreviation introduced more than once", Category.LANGUAGE, Severity.WARN,
      rationale="An abbreviation is taught once, at first use. A second 'Automated Driving System (ADS)' fifty pages later tells the reader you lost track of your own document.",
      fix="Keep the first definition, delete the later ones.")
def redefined_abbreviation(ctx):
    if _managed_by_package(ctx):
        return
    for acronym, occurrences in _definitions(ctx).items():
        if len(occurrences) < 2:
            continue
        first_offset = occurrences[0][0]
        first_f, first_line, _ = ctx.project.locate(first_offset)
        for offset, expansion, start, end, as_written in occurrences[1:]:
            f, line, col = ctx.project.locate(offset)
            yield ctx.finding("ABB001",
                              f"`{acronym}` was already introduced at {first_f}:{first_line}",
                              file=f, line=line, col=col,
                              context=f"{expansion} ({acronym})",
                              fix=f"Delete this expansion and write just `{acronym}`.",
                              edit=ctx.edit_span(start, end, as_written,
                                                 f"{expansion} ({as_written}) -> {as_written}"),
                              data={"acronym": acronym})


@rule("ABB002", "Abbreviation used before it is introduced", Category.LANGUAGE, Severity.WARN,
      rationale="A reader meeting 'ADS' before its expansion has to guess or search.",
      fix="Move the definition to the first use, or expand it there.")
def used_before_defined(ctx):
    if _managed_by_package(ctx):
        return
    definitions = _definitions(ctx)
    if not definitions:
        return
    ignored = _ignored(ctx)
    prose = ctx.project.prose
    for acronym, occurrences in definitions.items():
        if acronym in ignored:
            continue
        define_at = min(o[2] for o in occurrences)
        first_use = None
        for m in _ACRONYM_USE.finditer(prose):
            token = m.group(1).upper()
            if token != acronym:
                continue
            if m.start() >= define_at:
                break
            first_use = m.start()
            break
        if first_use is None:
            continue
        f, line, col = ctx.project.locate(first_use)
        def_f, def_line, _ = ctx.project.locate(define_at)
        yield ctx.finding("ABB002",
                          f"`{acronym}` is used here but only introduced later, at {def_f}:{def_line}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(first_use),
                          fix=f"Expand it at this first use and shorten the later one.",
                          data={"acronym": acronym})


@rule("ABB003", "Abbreviation introduced but never used", Category.LANGUAGE, Severity.INFO,
      rationale="Introducing an abbreviation you then never use costs the reader effort for nothing.",
      fix="Drop the parenthesised abbreviation and keep writing the term in full.")
def defined_but_unused(ctx):
    if _managed_by_package(ctx):
        return
    prose = ctx.project.prose
    uses = defaultdict(int)
    for m in _ACRONYM_USE.finditer(prose):
        uses[m.group(1).upper()] += 1
    min_uses = int(ctx.opt("ABB003", "min_uses", 2) or 2)
    for acronym, occurrences in _definitions(ctx).items():
        # The definition itself counts as one occurrence of the token.
        if uses.get(acronym, 0) >= min_uses:
            continue
        offset, expansion, _start = occurrences[0][:3]
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("ABB003",
                          f"`{acronym}` is introduced but then used {max(0, uses.get(acronym, 1) - 1)} time(s)",
                          file=f, line=line, col=col, context=f"{expansion} ({acronym})",
                          fix="Either use the abbreviation from here on, or do not introduce it.")


@rule("ABB004", "Abbreviation used without ever being introduced", Category.LANGUAGE, Severity.INFO,
      rationale="Field-specific abbreviations that were never expanded are the commonest reason an outside examiner stumbles.",
      fix="Expand it at first use, or add it to the ignore list in mechcheck.yaml if it is genuinely common knowledge.")
def used_never_defined(ctx):
    if _managed_by_package(ctx):
        return
    definitions = _definitions(ctx)
    ignored = _ignored(ctx)
    reported = set()
    for m in _ACRONYM_USE.finditer(ctx.project.prose):
        token = m.group(1).upper()
        if token in definitions or token in ignored or token in reported:
            continue
        if _NOT_ACRONYM.match(token):
            continue
        reported.add(token)
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("ABB004", f"`{token}` is used but never introduced",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=f"Write it out at first use: Full Term ({token}). "
                              f"If it needs no expansion, add it to rules.ABB004.ignore.",
                          data={"acronym": token})


@rule("ABB005", "Same abbreviation, different expansions", Category.LANGUAGE, Severity.WARN,
      rationale="Two expansions of one abbreviation means either a typo or two different concepts sharing a name.",
      fix="Settle on one expansion, or rename one of the concepts.")
def inconsistent_expansion(ctx):
    if _managed_by_package(ctx):
        return
    for acronym, occurrences in _definitions(ctx).items():
        variants = {}
        for offset, expansion, _start, _end, _as_written in occurrences:
            key = re.sub(r"[^a-z ]", "", expansion.lower()).strip()
            variants.setdefault(key, (offset, expansion))
        if len(variants) < 2:
            continue
        items = list(variants.values())
        offset, expansion = items[1]
        f, line, col = ctx.project.locate(offset)
        first = items[0][1]
        yield ctx.finding("ABB005",
                          f"`{acronym}` is expanded as both \"{first}\" and \"{expansion}\"",
                          file=f, line=line, col=col, context=f"{expansion} ({acronym})",
                          fix="Use a single expansion throughout.")
