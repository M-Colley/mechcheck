"""Venue packs: submission requirements as data.

Call-for-papers requirements change every year.  Encoding them in Python would
guarantee the checker is wrong by next cycle, so everything here reads from
``mechcheck/venues/<venue>.yaml``: the class, its options, the bibliography
style, the commands that must be present, and free-form required or forbidden
text patterns.  Adding a venue means adding a file.

Each pack carries a ``verified`` date.  VEN009 reminds you when a pack is old
enough that it should be re-read against the current call -- the tool's job is
to be reliable, and a confidently-stated stale page limit is the opposite.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime

from mechcheck.model import Category, Severity, rule


def _pack(ctx) -> dict:
    return ctx.config.venue_data or {}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v not in (None, "")]
    return [value]


def _class_options(ctx) -> list:
    _cls, options = ctx.project.documentclass()
    return [o.strip().lower() for o in options]


def _stage_key(ctx) -> str:
    """Venue packs describe requirements per stage: submission or final."""
    return "final" if ctx.config.stage == "final" else "submission"


@rule("VEN001", "Wrong document class for this venue", Category.POLICY, Severity.ERROR,
      rationale="Using the wrong template is an explicit desk-reject criterion at CHI and ASSETS.",
      fix="Switch to the class the venue's author guide specifies.")
def wrong_class(ctx):
    pack = _pack(ctx)
    expected = str(pack.get("document_class") or "").strip()
    if not expected:
        return
    actual, _options = ctx.project.documentclass()
    if actual.lower() == expected.lower():
        return
    cmds = ctx.project.commands("documentclass", 1)
    f, line, col = ctx.project.locate(cmds[0].start) if cmds else (ctx.project.main, None, None)
    yield ctx.finding("VEN001",
                      f"{pack.get('name', ctx.config.venue)} expects \\documentclass{{{expected}}}, "
                      f"this document uses {{{actual or 'nothing'}}}",
                      file=f, line=line, col=col,
                      fix=f"Use \\documentclass[...]{{{expected}}}.")


@rule("VEN002", "Document class options do not match the venue", Category.POLICY, Severity.ERROR,
      rationale="The submission and camera-ready formats differ by a few class options; the wrong ones produce a PDF in the wrong format entirely.",
      fix="Use the option set the venue specifies for this stage.")
def class_options(ctx):
    pack = _pack(ctx)
    stage = _stage_key(ctx)
    spec = (pack.get("class_options") or {}).get(stage) or {}
    if not spec:
        return
    present = _class_options(ctx)
    cmds = ctx.project.commands("documentclass", 1)
    f, line, col = ctx.project.locate(cmds[0].start) if cmds else (ctx.project.main, None, None)

    for option in _as_list(spec.get("required")):
        if str(option).lower() in present:
            continue
        yield ctx.finding("VEN002",
                          f"missing \\documentclass option `{option}` (required for {stage})",
                          file=f, line=line, col=col,
                          context=ctx.project.excerpt(cmds[0].start) if cmds else None,
                          fix=f"Add `{option}` to the class options.")

    for option in _as_list(spec.get("forbidden")):
        if str(option).lower() not in present:
            continue
        yield ctx.finding("VEN002",
                          f"\\documentclass option `{option}` must not be used for {stage}",
                          file=f, line=line, col=col,
                          fix=f"Remove `{option}`.")

    allowed = [str(o).lower() for o in _as_list(spec.get("one_of"))]
    if allowed and not any(o in present for o in allowed):
        yield ctx.finding("VEN002",
                          f"expected one of these class options for {stage}: {', '.join(allowed)}",
                          file=f, line=line, col=col,
                          fix=f"Add one of: {', '.join(allowed)}.")


@rule("VEN003", "Wrong bibliography style", Category.POLICY, Severity.ERROR,
      rationale="ACM venues require the ACM Reference Format; a different .bst produces a reference list the publisher will reject.",
      fix="Set the style the venue requires.")
def bibliography_style(ctx):
    pack = _pack(ctx)
    expected = str(pack.get("bibliography_style") or "").strip()
    if not expected:
        return
    cmds = ctx.project.commands("bibliographystyle", 1)
    if not cmds:
        # biblatex projects declare the style in the package options instead.
        packages = ctx.project.packages()
        if "biblatex" in packages:
            options = " ".join(packages["biblatex"]).lower()
            if expected.lower() in options:
                return
            yield ctx.finding("VEN003",
                              f"biblatex is used but the venue expects the {expected} style",
                              file=ctx.project.main,
                              fix=f"Use style={expected}, or switch to BibTeX with \\bibliographystyle{{{expected}}}.")
        return
    actual = cmds[0].arg(0).strip()
    if actual.lower() == expected.lower():
        return
    f, line, col = ctx.project.locate(cmds[0].start)
    yield ctx.finding("VEN003",
                      f"\\bibliographystyle{{{actual}}} but {pack.get('name', ctx.config.venue)} "
                      f"requires {{{expected}}}",
                      file=f, line=line, col=col,
                      fix=f"Change it to \\bibliographystyle{{{expected}}}.")


@rule("VEN004", "Required command missing", Category.POLICY, Severity.ERROR,
      rationale="Venues and publishers require specific commands (CCS concepts, keywords, highlights, author contributions); their absence stops the production pipeline.",
      fix="Add the command the venue requires.")
def required_commands(ctx):
    pack = _pack(ctx)
    for spec in _as_list(pack.get("required_commands")):
        if isinstance(spec, dict):
            name = str(spec.get("command") or spec.get("name") or "").strip()
            why = str(spec.get("why") or "")
            severity = spec.get("severity")
        else:
            name, why, severity = str(spec).strip(), "", None
        if not name:
            continue
        if ctx.project.commands(name.lstrip("\\"), 1) or ctx.project.environments(name.lstrip("\\")):
            continue
        yield ctx.finding("VEN004",
                          f"\\{name.lstrip(chr(92))} is required by {pack.get('name', ctx.config.venue)}"
                          + (f": {why}" if why else ""),
                          file=ctx.project.main,
                          severity=Severity.parse(severity, ctx.config.severity_for("VEN004")),
                          fix=f"Add \\{name.lstrip(chr(92))}{{...}}.")


@rule("VEN005", "Required statement missing", Category.POLICY, Severity.WARN,
      rationale="Publishers increasingly require named statements -- data availability, declaration of interest, CRediT roles, AI use. A missing one bounces the submission back at the worst moment.",
      fix="Add the statement the venue's author guide asks for.")
def required_statements(ctx):
    pack = _pack(ctx)
    prose = ctx.project.prose
    for spec in _as_list(pack.get("required_statements")):
        if not isinstance(spec, dict):
            continue
        pattern = spec.get("pattern")
        label = spec.get("name") or pattern
        if not pattern:
            continue
        try:
            found = re.search(str(pattern), prose, re.IGNORECASE)
        except re.error:
            continue
        if found:
            continue
        yield ctx.finding("VEN005",
                          f"no {label} found, which {pack.get('name', ctx.config.venue)} requires",
                          file=ctx.project.main,
                          severity=Severity.parse(spec.get("severity"),
                                                  ctx.config.severity_for("VEN005")),
                          fix=str(spec.get("fix") or f"Add a {label}."))


@rule("VEN006", "File name unsafe for the publisher's pipeline", Category.POLICY, Severity.ERROR,
      rationale="ACM's TAPS rejects source packages whose file names contain spaces or characters outside letters, digits, dash and underscore.",
      fix="Rename the file to use only A-Z a-z 0-9 - _ and a single dot before the extension.")
def unsafe_filenames(ctx):
    pack = _pack(ctx)
    if not pack.get("filename_charset_strict", False):
        return
    allowed = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9]+)?$")
    seen = set()
    for dirpath, dirnames, filenames in os.walk(ctx.root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("build", "out")]
        for name in filenames:
            if name.startswith("."):
                continue
            if allowed.match(name):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), ctx.root).replace(os.sep, "/")
            if rel in seen:
                continue
            seen.add(rel)
            reason = "contains a space" if " " in name else "contains characters TAPS rejects"
            yield ctx.finding("VEN006", f"`{rel}` {reason}", file=rel,
                              fix="Rename it: letters, digits, dash and underscore only.")
        if len(seen) > 25:
            return


@rule("VEN007", "Package not on the venue's accepted list", Category.POLICY, Severity.WARN,
      rationale="ACM TAPS compiles your sources itself and only supports an approved package list; an unsupported package fails at production, after acceptance.",
      fix="Replace it, or check the current accepted-packages list.")
def forbidden_packages(ctx):
    pack = _pack(ctx)
    forbidden = {str(p).lower() for p in _as_list(pack.get("forbidden_packages"))}
    if not forbidden:
        return
    for name in ctx.project.packages():
        if name.lower() not in forbidden:
            continue
        cmds = [c for c in ctx.project.commands("usepackage", 1) if name in c.arg(0)]
        offset = cmds[0].start if cmds else 0
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("VEN007", f"package `{name}` is not accepted by {pack.get('name', ctx.config.venue)}",
                          file=f, line=line, col=col,
                          fix=str(pack.get("forbidden_packages_fix")
                                  or "Check the venue's accepted package list and replace it."))


@rule("VEN008", "Venue pack has not been re-verified recently", Category.POLICY, Severity.INFO,
      rationale="Page limits and required statements change every cycle. A checker that states an outdated limit confidently is worse than one that admits it does not know.",
      fix="Open the current call for papers, confirm the values, and update the `verified` date in the venue pack.")
def stale_venue_pack(ctx):
    pack = _pack(ctx)
    if not pack:
        return
    verified = str(pack.get("verified") or "").strip()
    months = int(ctx.opt("VEN008", "max_age_months", 9) or 9)
    if not verified:
        yield ctx.finding("VEN008",
                          f"venue pack `{ctx.config.venue}` has no `verified` date",
                          file=ctx.project.main)
        return
    try:
        checked = datetime.strptime(verified, "%Y-%m-%d").date()
    except ValueError:
        return
    age_months = (date.today() - checked).days / 30.4
    if age_months < months:
        return
    source = pack.get("source_url") or ""
    yield ctx.finding("VEN008",
                      f"venue pack `{ctx.config.venue}` was last verified {verified} "
                      f"({age_months:.0f} months ago)",
                      file=ctx.project.main,
                      fix=f"Re-read {source or 'the current call for papers'} and update the pack.")


@rule("VEN009", "Text the venue does not allow", Category.POLICY, Severity.WARN,
      rationale="Some venues forbid specific content in a submission -- a visible author block, a non-anonymous repository link, a placeholder title.",
      fix="Remove or replace the offending text.")
def forbidden_text(ctx):
    pack = _pack(ctx)
    for spec in _as_list(pack.get("forbidden_text")):
        if not isinstance(spec, dict) or not spec.get("pattern"):
            continue
        try:
            pattern = re.compile(str(spec["pattern"]), re.IGNORECASE)
        except re.error:
            continue
        for m in list(pattern.finditer(ctx.project.text))[:5]:
            f, line, col = ctx.project.locate(m.start())
            yield ctx.finding("VEN009",
                              f"{spec.get('name', 'forbidden text')}: '{m.group(0)[:60]}'",
                              file=f, line=line, col=col,
                              severity=Severity.parse(spec.get("severity"),
                                                      ctx.config.severity_for("VEN009")),
                              fix=str(spec.get("fix") or "Remove it."))
