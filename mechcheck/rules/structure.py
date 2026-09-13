"""Document skeleton: headings, nesting, and files that do not exist."""

from __future__ import annotations

import re
from collections import Counter

from mechcheck.model import Category, Severity, rule

LEVELS = ["part", "chapter", "section", "subsection", "subsubsection", "paragraph"]

_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
                "nor", "of", "on", "onto", "or", "over", "the", "to", "up", "with", "via"}


def headings(ctx) -> list:
    """All sectioning commands in document order, with their level index."""
    cached = ctx.cache.get("headings")
    if cached is not None:
        return cached
    out = []
    for level, name in enumerate(LEVELS):
        for cmd in ctx.project.commands(name, 1):
            title = cmd.arg(0).strip()
            if title:
                out.append((cmd.start, level, name, title, cmd))
    out.sort()
    ctx.cache["headings"] = out
    return out


@rule("STR001", "Referenced file does not exist", Category.STRUCTURE, Severity.ERROR,
      rationale="A missing \\input is a chapter that silently is not in the PDF -- the failure mode nobody notices until the printed copy.",
      fix="Fix the path, or commit the file.")
def missing_input(ctx):
    from mechcheck.texsource import is_absolute_path

    for path, line, target in ctx.project.missing_inputs:
        # A file that exists under another capitalisation, or an absolute
        # path, is STR013's finding, with the more useful message.
        if is_absolute_path(target) or _case_variant(ctx, target):
            continue
        yield ctx.finding("STR001", f"\\input{{{target}}} could not be resolved",
                          file=path, line=line,
                          fix="Check the filename and that the file is committed (Overleaf is case-sensitive).")


def _input_candidates(target: str) -> list:
    from mechcheck.texsource import normalise_relpath

    typed = normalise_relpath(target)
    return [typed] if typed.lower().endswith(".tex") else [typed, typed + ".tex"]


def _case_variant(ctx, target: str):
    """The on-disk spelling of an \\input target when it differs only in case."""
    from mechcheck.texsource import find_case_insensitive

    for cand in _input_candidates(target):
        actual = find_case_insensitive(ctx.root, cand)
        if actual is None:
            continue
        return None if actual == cand else actual
    return None


#: The l2tabu list: packages that are unmaintained, produce worse output than
#: their successors, or clash with the packages everybody loads today.
_OBSOLETE_PACKAGES = {
    "subfigure": "subcaption",
    "epsfig": "graphicx", "psfig": "graphicx", "epsf": "graphicx",
    "times": "newtxtext and newtxmath (or mathptmx)", "mathptm": "mathptmx", "pslatex": "mathptmx",
    "palatino": "newpxtext and newpxmath (or mathpazo)", "mathpple": "mathpazo",
    "utopia": "fourier", "euler": "eulervm", "ae": "lmodern", "aecompl": "lmodern",
    "zefonts": "lmodern",
    "a4": "geometry", "a4wide": "geometry", "anysize": "geometry", "vmargin": "geometry",
    "t1enc": "fontenc with the T1 option", "isolatin": "inputenc", "isolatin1": "inputenc",
    "umlaut": "inputenc", "ucs": "nothing: UTF-8 input has been the default since 2018",
    "doublespace": "setspace", "fancyheadings": "fancyhdr",
    "scrpage": "scrlayer-scrpage", "scrpage2": "scrlayer-scrpage",
    "caption2": "caption", "glossary": "glossaries", "here": "float",
    "floatflt": "wrapfig", "picinpar": "wrapfig",
    "ngerman": "babel with the ngerman option", "german": "babel with the german option",
}


@rule("STR010", "Obsolete package", Category.STRUCTURE, Severity.WARN,
      rationale="These packages are on the l2tabu list of things not to load: unmaintained, worse than their replacements, in conflict with the packages everyone uses today -- and subfigure is refused outright by ACM's production pipeline.",
      fix="Load the replacement named in the finding.")
def obsolete_package(ctx):
    for c in ctx.project.commands("usepackage", 1):
        options = [o.strip().lower() for o in c.opt(0).split(",") if o.strip()]
        f, line, col = ctx.project.locate(c.start)
        for name in c.arg(0).split(","):
            name = name.strip()
            key = name.lower()
            if key in _OBSOLETE_PACKAGES:
                yield ctx.finding("STR010", f"package `{name}` is obsolete",
                                  file=f, line=line, col=col, context=ctx.project.excerpt(c.start),
                                  fix=f"Use {_OBSOLETE_PACKAGES[key]} instead.",
                                  data={"package": name})
            elif key == "inputenc" and "utf8x" in options:
                yield ctx.finding("STR010", "inputenc option `utf8x` (the ucs package) is obsolete",
                                  file=f, line=line, col=col, context=ctx.project.excerpt(c.start),
                                  fix="Use utf8, or delete the line: UTF-8 has been the default since 2018.",
                                  data={"package": "inputenc"})


@rule("STR011", "Package loaded more than once", Category.STRUCTURE, Severity.WARN,
      rationale="LaTeX ignores a second \\usepackage -- unless it carries options the first did not, in which case it stops with an 'Option clash' error that names neither line.",
      fix="Keep one \\usepackage line per package, with all of its options on it.")
def duplicate_package(ctx):
    from mechcheck.texsource import conditional_spans

    # A preamble that loads one of two option sets inside \if...\else...\fi
    # only ever loads one of them. Both branches are in the source; only one
    # is in the document.
    conditional = conditional_spans(ctx.project.text)

    def switched(pos: int) -> bool:
        return any(a <= pos < b for a, b in conditional)

    seen: dict = {}
    for c in ctx.project.commands("usepackage", 1):
        options = frozenset(o.strip().lower() for o in c.opt(0).split(",") if o.strip())
        for name in c.arg(0).split(","):
            key = name.strip().lower()
            if not key or key == "fontenc":
                continue  # fontenc is loaded once per encoding, legitimately
            if key not in seen:
                seen[key] = (c, options)
                continue
            first, first_options = seen[key]
            if switched(first.start) or switched(c.start):
                continue
            clash = bool(options - first_options)
            first_f, first_line, _ = ctx.project.locate(first.start)
            f, line, col = ctx.project.locate(c.start)
            yield ctx.finding("STR011",
                              f"`{key}` is already loaded at {first_f}:{first_line}"
                              + (" with different options: LaTeX will stop with an option clash" if clash else ""),
                              file=f, line=line, col=col, context=ctx.project.excerpt(c.start),
                              severity=ctx.config.severity_for("STR011") if clash else Severity.INFO,
                              fix=("Merge the options into the first \\usepackage and delete this one."
                                   if clash else "Delete this line."))


#: Packages that patch what hyperref patches, and only work loaded after it.
_AFTER_HYPERREF = ("cleveref", "glossaries", "glossaries-extra")


@rule("STR012", "Package loaded before hyperref that must follow it", Category.STRUCTURE,
      Severity.WARN,
      rationale="cleveref and glossaries redefine the same commands hyperref does, and only work when loaded after it; the wrong order breaks cross-references or their links without any error message.",
      fix="Move \\usepackage{hyperref} above it.")
def hyperref_order(ctx):
    loads = []
    for c in ctx.project.commands("usepackage", 1):
        for name in c.arg(0).split(","):
            loads.append((name.strip().lower(), c))
    hyperref = next((c for name, c in loads if name == "hyperref"), None)
    if hyperref is None:
        return  # loaded by the class or a local .sty we cannot see: say nothing
    for name, c in loads:
        if name not in _AFTER_HYPERREF or c.start > hyperref.start:
            continue
        f, line, col = ctx.project.locate(c.start)
        yield ctx.finding("STR012", f"`{name}` is loaded before hyperref",
                          file=f, line=line, col=col, context=ctx.project.excerpt(c.start),
                          fix=f"Load hyperref first, then {name}.")


@rule("STR013", "\\input path that will not resolve on Overleaf", Category.STRUCTURE, Severity.ERROR,
      rationale="Windows and macOS open Chapters/Intro.tex when the file is chapters/intro.tex, and an absolute path opens on exactly one computer. Overleaf and CI run Linux: the chapter silently vanishes from their PDF.",
      fix="Match the file name letter for letter, and keep every path relative to the project.")
def unportable_input(ctx):
    from mechcheck.texsource import TexProject, is_absolute_path

    for line in ctx.project.lines:
        if line.verbatim:
            continue
        for target in TexProject._child_inputs(line.code):
            if "\\" in target or "#" in target:
                continue  # built from a macro
            if is_absolute_path(target):
                yield ctx.finding("STR013", f"\\input{{{target[:60]}}} is an absolute path",
                                  file=line.file, line=line.lineno, context=line.raw.strip()[:90],
                                  fix="Copy the file into the project and reference it relatively.")
                continue
            actual = _case_variant(ctx, target)
            if not actual:
                continue
            yield ctx.finding("STR013",
                              f"`{target}` is stored as `{actual}`; Overleaf is case-sensitive and will not find it",
                              file=line.file, line=line.lineno, context=line.raw.strip()[:90],
                              fix=f"Write the name as `{actual}`, or rename the file to match.",
                              data={"typed": target, "actual": actual})


@rule("STR002", "Heading nesting skips a level", Category.STRUCTURE, Severity.WARN,
      rationale="Jumping from a section straight to a subsubsection breaks the table of contents and the document's logic.",
      fix="Insert the missing level, or promote the heading.")
def nesting_jump(ctx):
    previous = None
    for _start, level, name, title, cmd in headings(ctx):
        if previous is not None and level > previous + 1:
            f, line, col = ctx.project.locate(cmd.start)
            yield ctx.finding("STR002",
                              f"\\{name} \"{title[:40]}\" follows a \\{LEVELS[previous]} — a level is skipped",
                              file=f, line=line, col=col,
                              fix=f"Add a \\{LEVELS[previous + 1]}, or promote this heading.")
        previous = level


@rule("STR003", "Section with exactly one subsection", Category.STRUCTURE, Severity.INFO,
      rationale="A lone subsection has nothing to be distinguished from; it is a heading pretending to be structure.",
      fix="Merge it into its parent, or add its sibling.")
def only_child_subsection(ctx):
    items = headings(ctx)
    for i, (_start, level, name, title, cmd) in enumerate(items):
        children = []
        for _s2, level2, _n2, title2, cmd2 in items[i + 1:]:
            if level2 <= level:
                break
            if level2 == level + 1:
                children.append((title2, cmd2))
        if len(children) != 1:
            continue
        child_title, child_cmd = children[0]
        f, line, col = ctx.project.locate(child_cmd.start)
        yield ctx.finding("STR003",
                          f"\"{title[:35]}\" contains exactly one child: \"{child_title[:35]}\"",
                          file=f, line=line, col=col)


@rule("STR004", "Empty section", Category.STRUCTURE, Severity.WARN,
      rationale="A heading immediately followed by another heading is a placeholder that was never filled in.",
      fix="Write the section, or delete the heading.")
def empty_section(ctx):
    items = headings(ctx)
    minimum = int(ctx.opt("STR004", "min_words", 5) or 5)
    for i, (start, level, name, title, cmd) in enumerate(items):
        # A section that opens straight onto a subsection is ordinary writing,
        # not a placeholder. What matters is whether the whole subtree is empty:
        # find where this heading's descendants end, and count everything inside.
        stop = len(ctx.project.prose)
        for j in range(i + 1, len(items)):
            if items[j][1] <= level:
                stop = items[j][0]
                break
        body = ctx.project.prose[cmd.end:stop]
        # Remove the descendants' own titles so a heading cannot count as content.
        words = [w for w in re.split(r"\s+", body) if re.search(r"[A-Za-zÀ-ÿ]", w)]
        if len(words) >= minimum:
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("STR004",
                          f"\\{name} \"{title[:40]}\" and everything under it has "
                          f"{len(words)} words of text",
                          file=f, line=line, col=col)


@rule("STR005", "Inconsistent heading capitalisation", Category.STRUCTURE, Severity.INFO,
      rationale="Title Case in one heading and sentence case in the next is the most visible inconsistency in a table of contents.",
      fix="Pick one convention for all headings of the same level.")
def heading_case(ctx):
    # Compare like with like: sections in Title Case and subsections in
    # sentence case is a deliberate, common house style, and comparing across
    # levels reported every section in a real paper as wrong.
    by_level: dict = {}
    for heading in headings(ctx):
        if heading[1] >= 2:
            by_level.setdefault(heading[1], []).append(heading)
    for level_items in by_level.values():
        yield from _heading_case_within(ctx, level_items)


def _heading_case_within(ctx, items):
    def case_of(title: str):
        """True for Title Case, False for sentence case, None when undecidable.

        Only the words after the first carry the signal: the first word is
        capitalised in both conventions. A heading with nothing after it --
        "Motivation" -- or nothing but short words -- "Research Gap" -- is
        therefore both styles at once, and counting it as sentence case
        reported every one-word heading in a normal thesis as wrong.
        """
        words = [w for w in re.split(r"\s+", re.sub(r"[^\w\s'-]", "", title)) if w]
        content = [w for w in words[1:] if w.lower() not in _SMALL_WORDS and len(w) > 3]
        if not content:
            return None
        return sum(1 for w in content if w[0].isupper()) >= max(1, int(len(content) * 0.75))

    flags = [(cmd, title, case_of(title)) for _s, _l, _n, title, cmd in items]
    flags = [f for f in flags if f[2] is not None]
    if len(flags) < 4:
        return
    title_case = sum(1 for _c, _t, f in flags if f)
    if title_case in (0, len(flags)):
        return
    majority = title_case * 2 >= len(flags)
    for cmd, title, flag in flags:
        if flag == majority:
            continue
        f, line, col = ctx.project.locate(cmd.start)
        style = "Title Case" if majority else "sentence case"
        yield ctx.finding("STR005", f"heading \"{title[:45]}\" is not in {style}, unlike most others",
                          file=f, line=line, col=col, fix=f"Rewrite it in {style}.")


@rule("STR006", "Heading ends with a period", Category.STRUCTURE, Severity.INFO,
      rationale="Headings are labels, not sentences.",
      fix="Remove the trailing period.")
def heading_punctuation(ctx):
    for _start, _level, name, title, cmd in headings(ctx):
        if not title.rstrip().endswith("."):
            continue
        if title.rstrip().endswith(("etc.", "al.", "e.g.", "i.e.")):
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("STR006", f"\\{name} \"{title[:45]}\" ends with a period",
                          file=f, line=line, col=col)


@rule("STR007", "Duplicate heading title", Category.STRUCTURE, Severity.INFO,
      rationale="Two sections with the same name make cross-references ambiguous for the reader and for you.",
      fix="Differentiate the titles.")
def duplicate_headings(ctx):
    counts = Counter(title.strip().lower() for _s, _l, _n, title, _c in headings(ctx))
    for _start, _level, name, title, cmd in headings(ctx):
        key = title.strip().lower()
        if counts[key] < 2 or key in ("discussion", "limitations", "results", "method",
                                      "methods", "procedure", "participants", "apparatus",
                                      "measures", "summary", "conclusion", "introduction"):
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("STR007", f"\"{title[:45]}\" is used as a heading {counts[key]} times",
                          file=f, line=line, col=col)
        counts[key] = 0


@rule("STR008", "No abstract", Category.STRUCTURE, Severity.WARN,
      rationale="Every paper and thesis needs one; its absence usually means the file was never finished.",
      fix="Add \\begin{abstract} ... \\end{abstract}.")
def missing_abstract(ctx):
    if ctx.project.environments("abstract") or ctx.project.commands("abstract", 1):
        return
    if not ctx.project.commands("title", 1):
        return
    yield ctx.finding("STR008", "no abstract environment found", file=ctx.project.main)


@rule("STR009", "Bare heading number in a cross-reference sentence", Category.STRUCTURE,
      Severity.INFO,
      rationale="'as described above' and 'in the previous chapter' break when sections move; a real cross-reference does not.",
      fix="Replace with \\Cref{sec:...}.")
def vague_internal_reference(ctx):
    pattern = re.compile(
        r"\b(?:as (?:described|discussed|shown|explained) (?:above|below|earlier|previously)|"
        r"in the (?:previous|next|following|preceding) (?:section|chapter|subsection))\b",
        re.IGNORECASE)
    for m in pattern.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STR009", f"vague internal reference: '{m.group(0)}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))
