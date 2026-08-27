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
    for path, line, target in ctx.project.missing_inputs:
        yield ctx.finding("STR001", f"\\input{{{target}}} could not be resolved",
                          file=path, line=line,
                          fix="Check the filename and that the file is committed (Overleaf is case-sensitive).")


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
    minimum = int(ctx.opt("STR004", "min_words", 15) or 15)
    for i, (start, _level, name, title, cmd) in enumerate(items):
        stop = items[i + 1][0] if i + 1 < len(items) else len(ctx.project.prose)
        body = ctx.project.prose[cmd.end:stop]
        words = [w for w in re.split(r"\s+", body) if re.search(r"[A-Za-zÀ-ÿ]", w)]
        if len(words) >= minimum:
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("STR004", f"\\{name} \"{title[:40]}\" has {len(words)} words of text",
                          file=f, line=line, col=col)


@rule("STR005", "Inconsistent heading capitalisation", Category.STRUCTURE, Severity.INFO,
      rationale="Title Case in one heading and sentence case in the next is the most visible inconsistency in a table of contents.",
      fix="Pick one convention for all headings of the same level.")
def heading_case(ctx):
    items = [h for h in headings(ctx) if h[1] >= 2]
    if len(items) < 4:
        return
    def is_title_case(title: str) -> bool:
        words = [w for w in re.split(r"\s+", re.sub(r"[^\w\s'-]", "", title)) if w]
        content = [w for w in words[1:] if w.lower() not in _SMALL_WORDS and len(w) > 3]
        if not content:
            return False
        return sum(1 for w in content if w[0].isupper()) >= max(1, int(len(content) * 0.75))

    flags = [(cmd, title, is_title_case(title)) for _s, _l, _n, title, cmd in items]
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
