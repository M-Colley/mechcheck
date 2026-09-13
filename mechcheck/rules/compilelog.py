"""What the TeX log already told you, surfaced where you will read it.

Overleaf shows warnings behind a collapsed panel that most students never open,
and a thesis routinely compiles with 300 overfull boxes nobody has looked at.
Turning the log into ranked, counted findings is most of the value here; the
rest is knowing which warnings actually matter.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule

_OVERFULL = re.compile(r"^(Overfull|Underfull)\s+\\([hv])box\s+\((\d+(?:\.\d+)?)pt too (\w+)\)"
                       r"(?:.*?at lines? (\d+)(?:--(\d+))?)?", re.MULTILINE)
_UNDEFINED_REF = re.compile(r"LaTeX Warning: Reference `([^']+)' on page \S+ undefined", re.MULTILINE)
_UNDEFINED_CITE = re.compile(r"(?:LaTeX|Package natbib) Warning: Citation `([^']+)' on page \S+ undefined",
                             re.MULTILINE)
_MULTIPLY_DEFINED = re.compile(r"LaTeX Warning: Label `([^']+)' multiply defined", re.MULTILINE)
_MISSING_CHAR = re.compile(r"Missing character: There is no (\S+) .*?in font ([^!\n]+)", re.MULTILINE)
_FONT_SUB = re.compile(r"LaTeX Font Warning: Font shape `([^']+)' undefined", re.MULTILINE)
_ERROR = re.compile(r"^! (.+)$", re.MULTILINE)
_RERUN = re.compile(r"(Rerun to get|Label\(s\) may have changed)", re.MULTILINE)
_FILE_LINE = re.compile(r"^(?:\./)?(\S+\.tex):(\d+):", re.MULTILINE)


@rule("LOG001", "The document did not compile cleanly", Category.COMPILE, Severity.ERROR,
      needs_build=True,
      rationale="An error in the log means the PDF you are looking at is stale or incomplete.",
      fix="Read the first error; everything after it is usually a consequence.")
def compile_errors(ctx):
    if not ctx.log_text:
        return
    seen = set()
    for m in _ERROR.finditer(ctx.log_text):
        message = m.group(1).strip()
        if message in seen or message.startswith("=="):
            continue
        seen.add(message)
        file_hint, line_hint = _nearest_source(ctx.log_text, m.start())
        yield ctx.finding("LOG001", f"LaTeX error: {message}",
                          file=file_hint, line=line_hint,
                          fix="Fix this error first; later ones are often knock-on effects.")
        if len(seen) >= 10:
            break


@rule("LOG002", "Undefined references in the compiled document", Category.COMPILE, Severity.ERROR,
      needs_build=True,
      rationale="Each of these prints as '??' in the PDF.",
      fix="Define the label, or fix the key -- then compile twice.")
def undefined_references(ctx):
    if not ctx.log_text:
        return
    for key in sorted(set(_UNDEFINED_REF.findall(ctx.log_text))):
        yield ctx.finding("LOG002", f"reference `{key}` is undefined in the compiled PDF",
                          file=ctx.project.main, data={"label": key})


@rule("LOG003", "Undefined citations in the compiled document", Category.COMPILE, Severity.ERROR,
      needs_build=True,
      rationale="Each of these prints as '[?]' and is missing from the reference list.",
      fix="Add the entry, then run bibtex/biber and compile twice.")
def undefined_citations(ctx):
    if not ctx.log_text:
        return
    for key in sorted(set(_UNDEFINED_CITE.findall(ctx.log_text))):
        yield ctx.finding("LOG003", f"citation `{key}` is undefined in the compiled PDF",
                          file=ctx.project.main, data={"key": key})


@rule("LOG004", "Multiply defined labels", Category.COMPILE, Severity.ERROR,
      needs_build=True,
      rationale="References to a duplicated label silently point at whichever came last.",
      fix="Rename one of them.")
def multiply_defined(ctx):
    if not ctx.log_text:
        return
    for key in sorted(set(_MULTIPLY_DEFINED.findall(ctx.log_text))):
        yield ctx.finding("LOG004", f"label `{key}` is defined more than once",
                          file=ctx.project.main, data={"label": key})


@rule("LOG005", "Text overflowing the margin", Category.COMPILE, Severity.WARN,
      needs_build=True,
      rationale="An overfull hbox is text sticking out past the text block. A few are unavoidable; dozens mean nobody has looked at the printed page.",
      fix="Rewrite the line, add a hyphenation hint (\\-), or resize the offending table/URL.")
def overfull_boxes(ctx):
    if not ctx.log_text:
        return
    threshold_pt = float(ctx.opt("LOG005", "min_points", 5.0) or 5.0)
    max_reported = int(ctx.opt("LOG005", "max_reported", 15) or 15)

    bad = []
    for m in _OVERFULL.finditer(ctx.log_text):
        kind, box, size, direction, line_a, _line_b = m.groups()
        if kind != "Overfull" or box != "h":
            continue  # underfull boxes are a spacing aesthetic, not an error
        if float(size) < threshold_pt:
            continue
        bad.append((float(size), int(line_a) if line_a else None))
    if not bad:
        return
    bad.sort(reverse=True)
    for size, line in bad[:max_reported]:
        yield ctx.finding("LOG005", f"text overflows the margin by {size:.1f}pt",
                          file=ctx.project.main, line=line,
                          data={"points": size})
    if len(bad) > max_reported:
        yield ctx.finding("LOG005",
                          f"{len(bad) - max_reported} further overfull boxes over {threshold_pt}pt not listed",
                          file=ctx.project.main, severity=Severity.INFO)


@rule("LOG006", "Characters missing from the font", Category.COMPILE, Severity.ERROR,
      needs_build=True,
      rationale="A missing character prints as nothing at all -- a silently empty gap where a letter should be, typically an umlaut or a dash.",
      fix="Load the right font encoding (fontenc/inputenc), or switch to LuaLaTeX/XeLaTeX for Unicode.")
def missing_characters(ctx):
    if not ctx.log_text:
        return
    seen = set()
    for char, font in _MISSING_CHAR.findall(ctx.log_text):
        key = (char, font.strip())
        if key in seen:
            continue
        seen.add(key)
        yield ctx.finding("LOG006", f"character {char} is missing from font {font.strip()}",
                          file=ctx.project.main)
        if len(seen) >= 8:
            break


@rule("LOG007", "The document needs another compilation pass", Category.COMPILE, Severity.WARN,
      needs_build=True,
      rationale="Cross-references and the table of contents are one pass out of date, so the numbers you are reading may be wrong.",
      fix="Compile again (latexmk does this automatically).")
def rerun_needed(ctx):
    if not ctx.log_text or not _RERUN.search(ctx.log_text):
        return
    yield ctx.finding("LOG007", "LaTeX asked to be run again; the cross-references are stale",
                      file=ctx.project.main,
                      fix="Use latexmk, which reruns until stable.")


@rule("LOG008", "Undefined font shape", Category.COMPILE, Severity.INFO,
      needs_build=True,
      rationale="LaTeX substituted a different font, so the printed result is not the one you specified.",
      fix="Load a font package that provides the shape (e.g. bold small caps), or stop asking for it.")
def font_substitution(ctx):
    if not ctx.log_text:
        return
    for shape in sorted(set(_FONT_SUB.findall(ctx.log_text)))[:5]:
        yield ctx.finding("LOG008", f"font shape `{shape}` is undefined and was substituted",
                          file=ctx.project.main)



#: A class warning, with its continuation lines: acmart wraps long messages and
#: prefixes each continuation with "(acmart)".
_CLASS_WARNING = re.compile(
    r"^(?:Class|Package) (?P<who>[\w@-]+) Warning: (?P<message>.+?)"
    r"(?: on input line (?P<line>\d+))?\.?$", re.MULTILINE)

#: Warnings a source-level rule already reports, with the line number and a fix.
#: Reporting both would show the same problem twice.
_ALREADY_COVERED = (
    ("possible image without description", "ACC001"),
    ("images may lack descriptions", "ACC001"),
    ("no \\Description", "ACC001"),
)


@rule("LOG009", "The document class raised a warning", Category.COMPILE, Severity.WARN,
      needs_build=True,
      rationale="acmart and its peers check things no external tool can, and say so in a log nobody opens -- ACM's accessibility notice arrives this way and is routinely missed.",
      fix="Read the message: the class knows something about its own requirements that a linter cannot.")
def class_warnings(ctx):
    if not ctx.log_text:
        return
    # Ignore the noisy families that say nothing about the document.
    ignore_prefixes = ("microtype", "rerunfilecheck", "hyperref", "caption",
                       "epstopdf-base", "xcolor", "graphics", "Font")
    seen = set()
    for m in _CLASS_WARNING.finditer(ctx.log_text):
        who, message = m.group("who"), m.group("message").strip()
        if who in ignore_prefixes:
            continue
        lowered = message.lower()
        if any(needle in lowered and ctx.config.enabled(rule_id)
               for needle, rule_id in _ALREADY_COVERED):
            continue
        line = int(m.group("line")) if m.group("line") else None
        # The line is part of the identity: the same warning at two different
        # places is two problems, not one repeated message.
        key = (who, message[:80], line)
        if key in seen:
            continue
        seen.add(key)
        yield ctx.finding("LOG009", f"{who} says: {message[:160]}",
                          file=ctx.project.main, line=line,
                          data={"package": who})
        if len(seen) >= 12:
            return

_FLOAT_TOO_LARGE = re.compile(r"LaTeX Warning: Float too large for page by ([\d.]+)pt on input line (\d+)")


@rule("LOG010", "Float too large for the page", Category.COMPILE, Severity.WARN,
      needs_build=True,
      rationale="A figure or table taller than the text block is pushed to a page of its own, drags every later float along behind it, and can leave them all stacked at the end of the chapter.",
      fix="Scale the figure down (height as well as width), or split the table.")
def float_too_large(ctx):
    if not ctx.log_text:
        return
    seen = set()
    for size, line in _FLOAT_TOO_LARGE.findall(ctx.log_text):
        if (size, line) in seen:
            continue
        seen.add((size, line))
        yield ctx.finding("LOG010", f"a float is {float(size):.0f}pt too tall for the page",
                          file=ctx.project.main, line=int(line), data={"points": float(size)})
        if len(seen) >= 10:
            return


_PDF_STRING_TOKEN = re.compile(
    r"Package hyperref Warning: Token not allowed in a PDF string[^\n]*\n"
    r"\(hyperref\)\s+removing `([^'\n]*)' on input line (\d+)")


@rule("LOG011", "Heading text could not be used for a PDF bookmark", Category.COMPILE,
      Severity.INFO, needs_build=True,
      rationale="hyperref builds the PDF outline from the headings; a citation, a footnote or maths inside a heading cannot be represented there, so it is dropped and the bookmark reads wrongly.",
      fix="Give hyperref a plain-text version: \\section{\\texorpdfstring{$\\alpha$}{alpha} ...}, or move the citation out of the heading.")
def pdf_string_tokens(ctx):
    if not ctx.log_text:
        return
    seen = set()
    for token, line in _PDF_STRING_TOKEN.findall(ctx.log_text):
        if (token, line) in seen:
            continue
        seen.add((token, line))
        yield ctx.finding("LOG011", f"hyperref dropped `{token}` from a heading's bookmark",
                          file=ctx.project.main, line=int(line), data={"token": token})
        if len(seen) >= 8:
            return


def _nearest_source(log: str, position: int):
    """Best guess at the source file and line a log message refers to."""
    window = log[max(0, position - 2000):position + 400]
    hits = _FILE_LINE.findall(window)
    if hits:
        path, line = hits[-1]
        return path, int(line)
    return None, None
