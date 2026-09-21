"""The double-anonymous sweep.

Every one of these has desk-rejected somebody's paper.  They run only when the
document is in an anonymous stage -- ``profile: paper-anonymous``, a venue pack
that says review is double-anonymous, or ``anonymous`` in \\documentclass -- so
they stay silent for a camera-ready version where author names belong.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule

_SELF_REFERENCE = re.compile(
    r"\b(?:(?:in|from|of|see|cf\.?)\s+)?(?:our|the\s+authors'?)\s+"
    r"(?:previous|prior|earlier|own|recent|last|preliminary)\s+"
    r"(?:work|study|studies|paper|papers|research|publication|experiment|dataset)\b",
    re.IGNORECASE)

_IDENTIFYING_HOSTS = re.compile(
    r"https?://(?:www\.)?("
    r"github\.com/[\w.\-]+|gitlab\.com/[\w.\-]+|bitbucket\.org/[\w.\-]+|"
    r"osf\.io/\w+|figshare\.com/\S+|zenodo\.org/\S+|"
    r"[\w\-]+\.github\.io|researchgate\.net/\S+|linkedin\.com/\S+|"
    r"[\w\-]*\.uni-[\w\-]+\.de\S*|[\w\-]*\.ac\.[a-z]{2}\S*|[\w\-]*\.edu\S*"
    r")", re.IGNORECASE)

_FUNDING = re.compile(
    r"\b(funded by|grant (?:no\.?|number)|supported by the|Deutsche Forschungsgemeinschaft|"
    r"DFG|BMBF|European Union'?s? Horizon|ERC|NSF (?:grant|award))\b", re.IGNORECASE)


#: Environments acmart itself removes from an anonymous build. From the class:
#:
#:     \if@ACM@anonymous
#:       \excludecomment{anonsuppress}
#:       \excludecomment{acks}
#:
#: So text inside them is not merely styled differently -- it is not typeset at
#: all, and a reviewer cannot see it. Reporting it would be reporting the
#: correct construct as a mistake, which teaches people to stop using it.
_CLASS_SUPPRESSED_ENVS = ("acks", "anonsuppress")


def _class_hides_acks(ctx) -> bool:
    cls, options = ctx.project.documentclass()
    return cls.lower() == "acmart" and "anonymous" in [o.lower() for o in options]


def _suppressed_spans(ctx) -> list:
    """Offset ranges the document class will not typeset in this build."""
    if not _class_hides_acks(ctx):
        return []
    cached = ctx.cache.get("anon_suppressed_spans")
    if cached is None:
        cached = [(env.start, env.end)
                  for name in _CLASS_SUPPRESSED_ENVS
                  for env in ctx.project.environments(name)]
        ctx.cache["anon_suppressed_spans"] = cached
    return cached


def _is_suppressed(ctx, offset: int) -> bool:
    return any(start <= offset < end for start, end in _suppressed_spans(ctx))


def _is_anonymous_stage(ctx) -> bool:
    if ctx.config.anonymous:
        return True
    _cls, options = ctx.project.documentclass()
    if "anonymous" in [o.lower() for o in options]:
        return True
    model = str(ctx.config.venue_field("anonymity", "model", default="") or "").lower()
    return "double" in model or "anonymous" in model


@rule("ANON001", "Author identity present in an anonymous submission", Category.ANONYMITY,
      Severity.ERROR,
      rationale="Author names in a double-anonymous submission are the single most common desk reject.",
      fix="Add the `anonymous` class option -- acmart then replaces the author block automatically.")
def author_block_visible(ctx):
    if not _is_anonymous_stage(ctx):
        return
    _cls, options = ctx.project.documentclass()
    if "anonymous" in [o.lower() for o in options]:
        return  # acmart handles the substitution itself
    for name in ("author", "affiliation", "email", "orcid", "institution"):
        cmds = ctx.project.commands(name, 1)
        if not cmds:
            continue
        cmd = cmds[0]
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("ANON001",
                          f"\\{name} is present but the document is not compiled with the `anonymous` option",
                          file=f, line=line, col=col, context=ctx.project.excerpt(cmd.start),
                          fix="Use \\documentclass[manuscript,review,anonymous]{acmart}.")
        return


@rule("ANON002", "Acknowledgements left in an anonymous submission", Category.ANONYMITY,
      Severity.ERROR,
      rationale="Acknowledgements name colleagues, funders and institutions -- they identify the authors as reliably as the author block.",
      fix="Put them in acmart's acks environment, which the anonymous option removes for you; otherwise guard the section so it only appears in the camera-ready version.")
def acknowledgements_present(ctx):
    if not _is_anonymous_stage(ctx):
        return
    # acmart's own acks environment, under the anonymous option, is already
    # the fix this rule would ask for.
    hits = [] if _class_hides_acks(ctx) else list(ctx.project.environments("acks"))
    for cmd in ctx.project.any_commands(["acksname", "acknowledgments", "acknowledgements"], 1):
        hits.append(cmd)
    for cmd in ctx.project.any_commands(["section", "section*", "chapter"], 1):
        if re.search(r"acknowledge?ment|danksagung", cmd.arg(0), re.IGNORECASE):
            hits.append(cmd)
    hits = [h for h in hits if not _is_suppressed(ctx, h.start)]
    hits.sort(key=lambda h: h.start)
    for hit in hits[:1]:
        f, line, col = ctx.project.locate(hit.start)
        yield ctx.finding("ANON002", "an acknowledgements section is present",
                          file=f, line=line, col=col,
                          fix="Move it into \\begin{acks}...\\end{acks}, or remove it for review.")


@rule("ANON003", "Identifying link", Category.ANONYMITY, Severity.ERROR,
      rationale="A repository or project URL under your own account de-anonymises the submission in one click.",
      fix="Use an anonymised mirror (anonymous.4open.science, an anonymous OSF view-only link) for review.")
def identifying_link(ctx):
    if not _is_anonymous_stage(ctx):
        return
    allow = [str(a).lower() for a in (ctx.opt("ANON003", "allow", []) or [])]
    for m in _IDENTIFYING_HOSTS.finditer(ctx.project.text):
        url = m.group(0)
        if any(a in url.lower() for a in allow):
            continue
        if "anonymous" in url.lower():
            continue
        if _is_suppressed(ctx, m.start()):
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("ANON003", f"identifying link: {url[:70]}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("ANON004", "Funding statement in an anonymous submission", Category.ANONYMITY, Severity.WARN,
      rationale="A named grant identifies the group as precisely as a name does.",
      fix="Move the funding statement to the camera-ready version.")
def funding_statement(ctx):
    if not _is_anonymous_stage(ctx):
        return
    # One finding per line: a funding sentence trips several patterns at once.
    seen_lines = set()
    for m in _FUNDING.finditer(ctx.project.prose):
        if _is_suppressed(ctx, m.start()):
            continue
        f, line, col = ctx.project.locate(m.start())
        if (f, line) in seen_lines:
            continue
        seen_lines.add((f, line))
        yield ctx.finding("ANON004", f"funding mentioned: '{m.group(0)}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))
        if len(seen_lines) >= 3:
            return


@rule("ANON005", "Self-citation phrased in the first person", Category.ANONYMITY, Severity.WARN,
      rationale="'In our previous work [12]' tells the reviewer exactly who wrote this. Venues ask you to cite your own work in the third person instead.",
      fix="Rewrite as 'Prior work [12] showed ...'. Note that ASSETS explicitly asks you NOT to anonymise the citation itself.")
def first_person_self_citation(ctx):
    if not _is_anonymous_stage(ctx):
        return
    for m in _SELF_REFERENCE.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("ANON005", f"self-identifying phrase: '{m.group(0)}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("ANON006", "PDF metadata names the author", Category.ANONYMITY, Severity.ERROR,
      needs_build=True,
      rationale="Reviewers see the document properties. An anonymised body with your name in the PDF metadata is the classic near-miss.",
      fix="Clear the metadata: \\hypersetup{pdfauthor={}} , or let the anonymous class option do it.")
def pdf_metadata(ctx):
    if not _is_anonymous_stage(ctx) or not ctx.pdf_path:
        return
    try:
        with open(ctx.pdf_path, "rb") as fh:
            # A PDF carries the author in two unrelated places: the Info
            # dictionary and an XMP packet. Reading only the first and only
            # the first two megabytes left the commoner of the two unread.
            data = fh.read(32_000_000)
    except OSError:
        return
    for pattern in (rb"/Author\s*\(([^)]{1,200})\)",
                    rb"<pdf:Author>([^<]{1,200})</pdf:Author>",
                    rb"<dc:creator>.{0,200}?<rdf:li[^>]*>([^<]{1,200})</rdf:li>"):
        for m in re.finditer(pattern, data, re.DOTALL):
            value = m.group(1).decode("utf-8", errors="replace").strip()
            if not value or value.lower() in ("anonymous", "anonymous author(s)", "()"):
                continue
            where = "XMP metadata" if b"rdf" in pattern or b"pdf:" in pattern else "metadata"
            yield ctx.finding("ANON006", f"the PDF {where} author is \"{value[:60]}\"",
                              file=ctx.project.rel(ctx.pdf_path),
                              fix="Set \\hypersetup{pdfauthor={}} or compile with the anonymous option.")
            return


#: An author field that is nothing but "Anonymous" is a masked citation. A
#: title containing the word is not -- papers about anonymity exist.
_MASKED_AUTHOR = re.compile(r"^[\s{}]*anonymous\.?[\s{}]*$", re.IGNORECASE)

#: Phrases that mask a reference wherever they appear in the entry.
_MASKED_PHRASE = re.compile(
    r"\b(?:(?:removed|withheld|omitted|redacted|anonymi[sz]ed|blinded|suppressed)"
    r"\s+(?:for|during|pending)\s+(?:double[- ]?)?(?:blind\s+)?(?:review|blinding|submission)"
    r"|author(?:s)?(?:'|’)?\s+names?\s+(?:withheld|removed|omitted)"
    r"|reference\s+(?:removed|withheld|omitted)"
    r"|\[\s*(?:redacted|removed|anonymi[sz]ed|withheld)\s*\])", re.IGNORECASE)


@rule("ANON008", "Masked reference in the bibliography", Category.ANONYMITY, Severity.ERROR,
      rationale="CHI lists masked references as grounds for desk rejection: a reference a reviewer cannot resolve cannot be assessed, and the mask itself advertises that the work is the authors' own. Venues ask you to cite your own prior work in the third person instead.",
      fix="Restore the real reference and cite it in the third person -- 'Prior work [12] showed ...' rather than 'our earlier study'. The citation is not what de-anonymises a paper; writing about it in the first person is.")
def masked_reference(ctx):
    from mechcheck.rules.bib import entries

    if not _is_anonymous_stage(ctx):
        return
    for entry in entries(ctx):
        author = entry.get("author") or entry.get("editor")
        reason = None
        if author and _MASKED_AUTHOR.match(author):
            reason = f"the author field is \"{author.strip()}\""
        else:
            for field in ("author", "editor", "title", "booktitle", "journal", "note", "howpublished"):
                m = _MASKED_PHRASE.search(entry.get(field))
                if m:
                    reason = f"{field} says \"{m.group(0)}\""
                    break
        if not reason:
            continue
        yield ctx.finding("ANON008", f"`{entry.key}` is a masked reference: {reason}",
                          file=ctx.project.rel(entry.file), line=entry.line,
                          context=(entry.title or author or "")[:70],
                          data={"key": entry.key})


@rule("ANON007", "Anonymous option left in a camera-ready document", Category.ANONYMITY,
      Severity.ERROR,
      rationale="The mirror image of ANON001, and just as costly: the published version credits 'Anonymous Author(s)'.",
      fix="Remove `anonymous` (and `review`) from \\documentclass for the final version.")
def anonymous_option_in_final(ctx):
    if ctx.config.stage != "final" or ctx.config.anonymous:
        return
    cmds = ctx.project.commands("documentclass", 1)
    if not cmds:
        return
    options = [o.strip().lower() for o in cmds[0].opt(0).split(",")]
    leftover = [o for o in ("anonymous", "review") if o in options]
    if not leftover:
        return
    f, line, col = ctx.project.locate(cmds[0].start)
    yield ctx.finding("ANON007",
                      f"\\documentclass still has: {', '.join(leftover)}",
                      file=f, line=line, col=col, context=ctx.project.excerpt(cmds[0].start),
                      fix="Switch to the camera-ready options for your venue.")
