"""Thesis formalities.

These are the things that are not in the marking criteria but will still cost a
student a week: a missing declaration of originality, an abstract in only one
language, front matter in the wrong order.  They vary between universities, so
every requirement here is switchable from ``mechcheck.yaml``; the defaults
follow common German computer-science practice.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule

_DECLARATION = re.compile(
    r"(eigenst[äa]ndigkeitserkl[äa]rung|selbst[äa]ndigkeitserkl[äa]rung|"
    r"erkl[äa]rung\s+zur\s+(?:selbst[äa]ndigen|eigenst[äa]ndigen)|"
    r"declaration\s+of\s+(?:originality|authorship|academic\s+integrity)|"
    r"statement\s+of\s+originality|ich\s+versichere|hiermit\s+erkl[äa]re\s+ich)",
    re.IGNORECASE)

_AI_CLAUSE = re.compile(
    r"(hilfsmittel|aids|generative\s+ai|k[üu]nstliche[rn]?\s+intelligenz|"
    r"large\s+language\s+model|llm|chatgpt|ai[- ]?tools?)", re.IGNORECASE)

_GERMAN_MARKERS = re.compile(
    r"\b(und|der|die|das|nicht|werden|wurde|Untersuchung|Ergebnisse|Zusammenfassung)\b")


def _is_thesis(ctx) -> bool:
    if ctx.config.profile.startswith("thesis"):
        return True
    return ctx.project.is_thesis_like()


@rule("THE001", "No declaration of originality", Category.STRUCTURE, Severity.ERROR,
      applies_to="thesis",
      rationale="Nearly every German examination regulation requires a signed declaration; a thesis submitted without one can be rejected on formal grounds alone.",
      fix="Add the declaration your examination office prescribes, including the clause on permitted aids.")
def declaration_missing(ctx):
    if not _is_thesis(ctx):
        return
    if not bool(ctx.opt("THE001", "required", True)):
        return
    if _DECLARATION.search(ctx.project.prose) or _DECLARATION.search(ctx.project.text):
        return
    yield ctx.finding("THE001", "no declaration of originality (Eigenständigkeitserklärung) found",
                      file=ctx.project.main,
                      fix="Copy the exact wording from your examination office and add it as the last page.")


@rule("THE002", "Declaration does not mention permitted aids or AI", Category.STRUCTURE,
      Severity.WARN, applies_to="thesis",
      rationale="Most universities have added a clause on generative AI to the standard declaration; using last year's template silently omits it.",
      fix="Use the current wording from your examination office.")
def declaration_ai_clause(ctx):
    if not _is_thesis(ctx):
        return
    match = _DECLARATION.search(ctx.project.prose)
    if not match:
        return  # THE001 reports the absence
    window = ctx.project.prose[match.start():match.start() + 2500]
    if _AI_CLAUSE.search(window):
        return
    f, line, col = ctx.project.locate(match.start())
    yield ctx.finding("THE002",
                      "the declaration does not mention permitted aids or generative AI",
                      file=f, line=line, col=col,
                      fix="Check whether your university's current declaration includes an AI clause.")


@rule("THE003", "Abstract in only one language", Category.STRUCTURE, Severity.WARN,
      applies_to="thesis",
      rationale="German CS programmes almost always require both a German Zusammenfassung and an English abstract.",
      fix="Add the missing one.")
def bilingual_abstract(ctx):
    if not _is_thesis(ctx):
        return
    if not bool(ctx.opt("THE003", "required", True)):
        return
    text = ctx.project.text
    has_german = bool(re.search(r"\\(chapter|section|section\*|chapter\*)\s*\{[^}]*"
                                r"(Zusammenfassung|Kurzfassung|Abstrakt)", text, re.IGNORECASE))
    has_english = bool(ctx.project.environments("abstract")) or bool(
        re.search(r"\\(chapter|section|section\*|chapter\*)\s*\{[^}]*Abstract", text, re.IGNORECASE))
    if has_german and has_english:
        return
    if not has_german and not has_english:
        return  # STR008 covers "no abstract at all"
    missing = "German (Zusammenfassung)" if has_english else "English (Abstract)"
    yield ctx.finding("THE003", f"only one abstract found; the {missing} one is missing",
                      file=ctx.project.main)


@rule("THE004", "No list of figures or tables", Category.STRUCTURE, Severity.INFO,
      applies_to="thesis",
      rationale="Once a document has a dozen floats, examiners expect to be able to find them from the front matter.",
      fix="Add \\listoffigures and \\listoftables after the table of contents.")
def missing_lists(ctx):
    if not _is_thesis(ctx):
        return
    floats = ctx.project.floats()
    threshold = int(ctx.opt("THE004", "min_floats", 8) or 8)
    if len(floats) < threshold:
        return
    text = ctx.project.text
    missing = []
    if not re.search(r"\\listoffigures", text) and sum(
            1 for e in floats if e.name.startswith("figure")) >= threshold:
        missing.append("\\listoffigures")
    if not re.search(r"\\listoftables", text) and sum(
            1 for e in floats if e.name.startswith("table")) >= threshold:
        missing.append("\\listoftables")
    if not missing:
        return
    yield ctx.finding("THE004", f"{len(floats)} floats but no {' or '.join(missing)}",
                      file=ctx.project.main)


@rule("THE005", "No table of contents", Category.STRUCTURE, Severity.WARN, applies_to="thesis",
      rationale="A thesis without a table of contents is unreadable as a document and unmarkable as an artefact.",
      fix="Add \\tableofcontents after the title page.")
def missing_toc(ctx):
    if not _is_thesis(ctx):
        return
    if re.search(r"\\tableofcontents", ctx.project.text):
        return
    yield ctx.finding("THE005", "no \\tableofcontents found", file=ctx.project.main)


@rule("THE006", "Chapter with no content of its own", Category.STRUCTURE, Severity.INFO,
      applies_to="thesis",
      rationale="A chapter that opens straight onto its first section gives the reader no idea what is coming.",
      fix="Write two or three sentences under the chapter heading saying what the chapter does.")
def chapter_without_preamble(ctx):
    if not _is_thesis(ctx):
        return
    chapters = ctx.project.commands("chapter", 1)
    sections = ctx.project.commands("section", 1)
    if not chapters:
        return
    minimum = int(ctx.opt("THE006", "min_words", 25) or 25)
    for chapter in chapters:
        following = [s for s in sections if s.start > chapter.start]
        if not following:
            continue
        body = ctx.project.prose[chapter.end:following[0].start]
        words = [w for w in re.split(r"\s+", body) if re.search(r"[A-Za-zÀ-ÿ]", w)]
        if len(words) >= minimum:
            continue
        f, line, col = ctx.project.locate(chapter.start)
        yield ctx.finding("THE006",
                          f"chapter \"{chapter.arg(0)[:40]}\" goes straight into its first section",
                          file=f, line=line, col=col,
                          fix="Add a short paragraph outlining the chapter.")


@rule("THE007", "Mixed languages in the running text", Category.LANGUAGE, Severity.INFO,
      applies_to="thesis",
      rationale="A thesis written in English with German paragraphs left in (or the reverse) usually means text was reused without translation.",
      fix="Translate the stray passages.")
def mixed_language(ctx):
    if not _is_thesis(ctx):
        return
    language = ctx.config.language.lower()
    if not language.startswith("en"):
        return
    for line in ctx.project.lines:
        if line.verbatim or len(line.code.strip()) < 60:
            continue
        hits = _GERMAN_MARKERS.findall(line.code)
        if len(hits) < 4:
            continue
        yield ctx.finding("THE007", "this line looks like German in an English document",
                          file=line.file, line=line.lineno, context=line.raw.strip()[:90])
