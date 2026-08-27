"""Figure descriptions and accessible output.

ACM requires alt text for every figure, and its TAPS pipeline validates it.
ASSETS goes further: an inaccessible submission is desk-rejected outright.
That makes these the rules with the sharpest consequences in the whole tool,
and the ones most worth catching months before the deadline.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule
from mechcheck.texsource import parse_commands

#: Descriptions that technically exist but describe nothing.
_PLACEHOLDER = re.compile(
    r"^\s*(?:an?\s+)?(image|figure|picture|screenshot|photo|diagram|graph|chart|plot|table|"
    r"illustration|overview|example|result|results|todo|tbd|description|alt text)\s*\.?\s*$",
    re.IGNORECASE)

_COLOUR_ONLY = re.compile(
    r"\b(?:the\s+)?(red|green|blue|orange|yellow|purple|pink|grey|gray|black|white|cyan|magenta)\s+"
    r"(line|bar|curve|area|region|dot|point|marker|box|circle|square|triangle|shading|band)s?\b",
    re.IGNORECASE)


def _uses_acmart(ctx) -> bool:
    cls, _ = ctx.project.documentclass()
    return cls.lower() == "acmart"


def _required(ctx) -> bool:
    """Descriptions required by the venue pack, or by acmart being in use."""
    venue_requires = ctx.config.venue_field("accessibility", "descriptions_required", default=None)
    if venue_requires is not None:
        return bool(venue_requires)
    return _uses_acmart(ctx)


@rule("ACC001", "Figure without a \\Description", Category.ACCESSIBILITY, Severity.ERROR,
      rationale="ACM requires alt text for every figure and validates it in TAPS; at ASSETS an inaccessible submission is desk-rejected.",
      fix="Add \\Description{...} inside the figure: say what the figure shows and what the reader should conclude from it.")
def missing_description(ctx):
    if not _required(ctx):
        return
    text = ctx.project.text
    for env in ctx.project.floats():
        if not env.name.startswith("figure"):
            continue
        if parse_commands(env.body(text), "Description", 1):
            continue
        f, line, col = ctx.project.locate(env.start)
        caption = parse_commands(env.body(text), "caption", 1)
        hint = caption[0].arg(0)[:50] if caption else ""
        yield ctx.finding("ACC001", "figure has no \\Description (alt text)",
                          file=f, line=line, col=col, context=hint,
                          fix="Add \\Description{...}: what is shown, and what it demonstrates.")


@rule("ACC002", "\\Description is a placeholder", Category.ACCESSIBILITY, Severity.ERROR,
      rationale="'A figure.' satisfies the syntax and helps nobody; it is worse than nothing because it silences the check.",
      fix="Describe the content: axes, trend, and the point the figure makes.")
def placeholder_description(ctx):
    text = ctx.project.text
    minimum = int(ctx.opt("ACC002", "min_words", 8) or 8)
    for env in ctx.project.floats():
        for cmd in parse_commands(env.body(text), "Description", 1):
            body = cmd.arg(0).strip()
            words = [w for w in re.split(r"\s+", body) if w]
            if not (_PLACEHOLDER.match(body) or len(words) < minimum):
                continue
            offset = env.body_start + cmd.start
            f, line, col = ctx.project.locate(offset)
            reason = "is a placeholder" if _PLACEHOLDER.match(body) else f"is only {len(words)} words"
            yield ctx.finding("ACC002", f"\\Description {reason}",
                              file=f, line=line, col=col, context=body[:70],
                              fix=f"Write at least {minimum} words describing what the figure shows.")


@rule("ACC003", "\\Description repeats the caption", Category.ACCESSIBILITY, Severity.WARN,
      rationale="A screen-reader user hears the caption already; repeating it verbatim adds nothing they did not have.",
      fix="Describe what is visually in the figure, which the caption does not say.")
def description_duplicates_caption(ctx):
    from mechcheck.bibtex import similarity

    text = ctx.project.text
    for env in ctx.project.floats():
        body = env.body(text)
        caps = parse_commands(body, "caption", 1)
        descs = parse_commands(body, "Description", 1)
        if not caps or not descs:
            continue
        score = similarity(caps[0].arg(0), descs[0].arg(0))
        if score < 0.9:
            continue
        offset = env.body_start + descs[0].start
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("ACC003", f"\\Description is essentially the caption again ({score:.2f} similar)",
                          file=f, line=line, col=col, context=descs[0].arg(0)[:70])


@rule("ACC004", "Meaning carried by colour alone", Category.ACCESSIBILITY, Severity.WARN,
      rationale="'the red line' is unreadable to a colour-blind reader and to anyone printing in greyscale -- about 8% of male readers.",
      fix="Add a second cue: 'the red dashed line (baseline)'.")
def colour_only_reference(ctx):
    prose = ctx.project.prose
    for m in _COLOUR_ONLY.finditer(prose):
        window = prose[max(0, m.start() - 60):m.end() + 60].lower()
        # A second, non-colour cue nearby makes this fine.
        if re.search(r"\b(dashed|dotted|solid|hatch|striped|triangle|circle|square|marker|"
                     r"pattern|thick|thin|label(l)?ed)\b", window):
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("ACC004", f"'{m.group(0)}' identifies data by colour alone",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("ACC005", "Complex table without a description", Category.ACCESSIBILITY, Severity.INFO,
      rationale="ACM suggests describing the structure of complex tables so a screen reader can convey the layout.",
      fix="Add \\Description{...} summarising what the table contains.")
def table_without_description(ctx):
    if not _required(ctx):
        return
    text = ctx.project.text
    for env in ctx.project.floats():
        if not env.name.startswith("table"):
            continue
        body = env.body(text)
        if parse_commands(body, "Description", 1):
            continue
        rows = body.count("\\\\")
        if rows < int(ctx.opt("ACC005", "min_rows", 6) or 6):
            continue
        f, line, col = ctx.project.locate(env.start)
        yield ctx.finding("ACC005", f"table with about {rows} rows has no \\Description",
                          file=f, line=line, col=col)


@rule("ACC006", "PDF is not tagged", Category.ACCESSIBILITY, Severity.WARN, needs_build=True,
      rationale="An untagged PDF has no reading order, so assistive technology cannot navigate it. ASSETS requires an accessible PDF at submission.",
      fix="Compile with a recent acmart (which sets pdfmanagement/tagging), or run the publisher's accessibility pipeline.")
def untagged_pdf(ctx):
    path = ctx.pdf_path
    if not path:
        return
    try:
        with open(path, "rb") as fh:
            data = fh.read(4_000_000)
    except OSError:
        return
    if re.search(rb"/Marked\s*true", data):
        return
    yield ctx.finding("ACC006", "the compiled PDF does not declare itself as tagged (/MarkInfo /Marked true)",
                      file=ctx.project.rel(path),
                      fix="Enable PDF tagging in the template, or check accessibility before submitting.")


@rule("ACC007", "Figure text likely too small", Category.ACCESSIBILITY, Severity.INFO,
      rationale="A figure scaled below about half its natural width usually carries axis labels too small to read in print.",
      fix="Redraw the figure at the size it will be printed rather than scaling it down.")
def small_scaled_figure(ctx):
    for cmd in ctx.project.commands("includegraphics", 1):
        opts = " ".join(cmd.opts)
        m = re.search(r"(?:width\s*=\s*)?([0-9]*\.?[0-9]+)\s*\\(?:line|column|text)width", opts)
        scale = None
        if m:
            scale = float(m.group(1))
        else:
            m2 = re.search(r"scale\s*=\s*([0-9]*\.?[0-9]+)", opts)
            if m2:
                scale = float(m2.group(1))
        if scale is None or scale >= float(ctx.opt("ACC007", "min_scale", 0.4) or 0.4):
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("ACC007", f"graphic scaled to {scale:g} of the text width",
                          file=f, line=line, col=col, context=ctx.project.excerpt(cmd.start))
