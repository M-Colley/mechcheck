"""Figures, tables and captions.

The single highest-yield check in this file is FIG003: a float nobody ever
refers to.  It is invisible while writing, obvious to a reader, and a reliable
signal that a figure was pasted in and forgotten.
"""

from __future__ import annotations

import os
import re

from mechcheck.model import Category, Severity, rule
from mechcheck.texsource import parse_commands

_LABEL_PREFIX = {
    "figure": ("fig", "figure"),
    "figure*": ("fig", "figure"),
    "wrapfigure": ("fig", "figure"),
    "sidewaysfigure": ("fig", "figure"),
    "table": ("tab", "table"),
    "table*": ("tab", "table"),
    "sidewaystable": ("tab", "table"),
    "listing": ("lst", "listing", "code"),
    "algorithm": ("alg", "algo", "algorithm"),
    "algorithm*": ("alg", "algo", "algorithm"),
}

_REF_CMDS = ["ref", "cref", "Cref", "autoref", "vref", "pageref", "eqref", "nameref",
             "labelcref", "subref", "Autoref"]


def _label_of(env, text: str):
    labels = parse_commands(env.body(text), "label", 1)
    return labels[0].arg(0).strip() if labels else None


def _captions_of(env, text: str):
    return parse_commands(env.body(text), "caption", 1)


def _referenced_labels(ctx) -> set:
    out = set()
    for cmd in ctx.project.any_commands(_REF_CMDS, 1):
        for key in cmd.arg(0).split(","):
            key = key.strip()
            if key:
                out.add(key)
    return out


@rule("FIG001", "Float without a caption", Category.FLOATS, Severity.WARN,
      rationale="A figure or table with no caption cannot be read on its own, and the list of figures will be wrong.",
      fix="Add \\caption{...} inside the environment.")
def no_caption(ctx):
    for env in ctx.project.floats():
        if env.name in ("algorithm", "algorithm*"):
            continue  # algorithm packages have their own caption command
        if _captions_of(env, ctx.project.text):
            continue
        f, line, col = ctx.project.locate(env.start)
        yield ctx.finding("FIG001", f"\\begin{{{env.name}}} has no \\caption",
                          file=f, line=line, col=col, context=ctx.project.excerpt(env.start),
                          fix="Add \\caption{...} (and a \\label after it).")


@rule("FIG002", "Float without a label", Category.FLOATS, Severity.WARN,
      rationale="Without a label the float cannot be referenced, so it will end up orphaned in the text.",
      fix="Add \\label{fig:...} directly after the \\caption.")
def no_label(ctx):
    for env in ctx.project.floats():
        if _label_of(env, ctx.project.text):
            continue
        f, line, col = ctx.project.locate(env.start)
        yield ctx.finding("FIG002", f"\\begin{{{env.name}}} has no \\label",
                          file=f, line=line, col=col, context=ctx.project.excerpt(env.start),
                          fix="Add \\label{...} on the line after \\caption{...}.")


@rule("FIG003", "Float never referenced in the text", Category.FLOATS, Severity.WARN,
      rationale="Every figure and table must be discussed in the running text; an unreferenced float is either redundant or an oversight.",
      fix="Refer to it (\\Cref{...}) where you discuss it, or delete the float.")
def unreferenced_float(ctx):
    referenced = _referenced_labels(ctx)
    for env in ctx.project.floats():
        label = _label_of(env, ctx.project.text)
        if not label or label in referenced:
            continue
        f, line, col = ctx.project.locate(env.start)
        yield ctx.finding("FIG003", f"{env.name} `{label}` is never referenced in the text",
                          file=f, line=line, col=col, context=ctx.project.excerpt(env.start),
                          fix=f"Add a reference such as \\Cref{{{label}}} where you discuss it.",
                          data={"label": label})


@rule("FIG004", "\\label before \\caption", Category.FLOATS, Severity.ERROR,
      rationale="LaTeX numbers a label from the last counter step, so a label placed before its caption silently points at the wrong number.",
      fix="Move \\label{...} to immediately after \\caption{...}.")
def label_before_caption(ctx):
    text = ctx.project.text
    for env in ctx.project.floats():
        body = env.body(text)
        caps = parse_commands(body, "caption", 1)
        labs = parse_commands(body, "label", 1)
        if not caps or not labs:
            continue
        if labs[0].start < caps[0].start:
            offset = env.body_start + labs[0].start
            f, line, col = ctx.project.locate(offset)
            yield ctx.finding("FIG004",
                              f"\\label comes before \\caption in this {env.name}; the reference will show the wrong number",
                              file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                              fix="Put \\label{...} after \\caption{...}.")


@rule("FIG005", "Caption does not end with a period", Category.FLOATS, Severity.INFO,
      rationale="Caption punctuation is a house-style decision; being inconsistent about it looks careless.",
      fix="End every caption with a period, or none of them.")
def caption_punctuation(ctx):
    caps = []
    for env in ctx.project.floats():
        for cap in _captions_of(env, ctx.project.text):
            body = cap.arg(0).strip()
            if body:
                caps.append((env, cap, body))
    if len(caps) < 3:
        return
    ends_with_period = sum(1 for _e, _c, b in caps if b.rstrip().endswith((".", "!", "?")))
    # Report only the minority: whichever convention the document mostly uses wins.
    majority_has_period = ends_with_period * 2 >= len(caps)
    for env, cap, body in caps:
        has = body.rstrip().endswith((".", "!", "?"))
        if has == majority_has_period:
            continue
        offset = env.body_start + cap.start
        f, line, col = ctx.project.locate(offset)
        want = "end with a period" if majority_has_period else "not end with a period"
        yield ctx.finding("FIG005",
                          f"Caption punctuation is inconsistent: {len(caps) - min(ends_with_period, len(caps) - ends_with_period)} "
                          f"of {len(caps)} captions {want}, this one differs",
                          file=f, line=line, col=col, context=body[:80],
                          fix=f"Make this caption {want}.")


@rule("FIG006", "Label prefix does not match the float type", Category.FLOATS, Severity.INFO,
      rationale="fig:/tab: prefixes make cross-references readable and make a mismatched \\ref obvious at a glance.",
      fix="Rename the label to the conventional prefix for its environment.")
def label_prefix(ctx):
    for env in ctx.project.floats():
        label = _label_of(env, ctx.project.text)
        prefixes = _LABEL_PREFIX.get(env.name)
        if not label or not prefixes or ":" not in label:
            continue
        prefix = label.split(":", 1)[0].strip().lower()
        if prefix in prefixes:
            continue
        f, line, col = ctx.project.locate(env.start)
        yield ctx.finding("FIG006",
                          f"{env.name} is labelled `{label}` but the convention here is `{prefixes[0]}:`",
                          file=f, line=line, col=col,
                          fix=f"Rename to `{prefixes[0]}:{label.split(':', 1)[1]}`.")


@rule("FIG007", "Graphic without a width", Category.FLOATS, Severity.INFO,
      rationale="An \\includegraphics with no width or scale renders at the image's native size and silently overflows the text block.",
      fix="Add [width=\\linewidth] or [width=0.8\\columnwidth].")
def graphic_without_width(ctx):
    for cmd in ctx.project.commands("includegraphics", 1):
        opts = " ".join(cmd.opts).lower()
        if any(k in opts for k in ("width", "height", "scale", "totalheight")):
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("FIG007", f"\\includegraphics{{{cmd.arg(0)}}} has no width or scale",
                          file=f, line=line, col=col, context=ctx.project.excerpt(cmd.start),
                          fix="Add [width=\\linewidth].")


@rule("FIG008", "Graphics file not found", Category.FLOATS, Severity.ERROR,
      rationale="A missing image compiles to a black box on Overleaf and stops the build in CI.",
      fix="Check the path, the extension and the capitalisation -- Overleaf is case-sensitive, Windows is not.")
def missing_graphic(ctx):
    roots = [ctx.root]
    for cmd in ctx.project.commands("graphicspath", 1):
        for m in re.finditer(r"\{([^{}]+)\}", cmd.arg(0)):
            roots.append(os.path.join(ctx.root, m.group(1)))

    extensions = ["", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".PDF", ".PNG", ".JPG"]
    for cmd in ctx.project.commands("includegraphics", 1):
        name = cmd.arg(0).strip()
        if not name or "\\" in name or "#" in name:
            continue  # built from a macro; we cannot resolve it statically
        found = False
        for base in roots:
            for ext in extensions:
                if os.path.isfile(os.path.normpath(os.path.join(base, name + ext))):
                    found = True
                    break
            if found:
                break
        if found:
            continue
        f, line, col = ctx.project.locate(cmd.start)
        yield ctx.finding("FIG008", f"graphics file `{name}` not found",
                          file=f, line=line, col=col, context=ctx.project.excerpt(cmd.start),
                          fix="Fix the path, or commit the missing file.")


@rule("FIG009", "Two floats share a caption", Category.FLOATS, Severity.INFO,
      rationale="Identical captions almost always mean a figure was duplicated and one copy never updated.",
      fix="Give each float a caption describing what is specific to it.")
def duplicate_captions(ctx):
    seen = {}
    for env in ctx.project.floats():
        for cap in _captions_of(env, ctx.project.text):
            key = re.sub(r"\s+", " ", cap.arg(0).strip().lower())
            if len(key) < 12:
                continue
            offset = env.body_start + cap.start
            if key in seen:
                f, line, col = ctx.project.locate(offset)
                first_f, first_line, _ = ctx.project.locate(seen[key])
                yield ctx.finding("FIG009",
                                  f"caption is identical to the one at {first_f}:{first_line}",
                                  file=f, line=line, col=col, context=cap.arg(0)[:80],
                                  fix="Differentiate the two captions.")
            else:
                seen[key] = offset


@rule("FIG010", "Table caption placed below the table", Category.FLOATS, Severity.INFO,
      rationale="Table captions go above the table and figure captions below it; mixing the two is a formatting slip reviewers notice.",
      fix="Move \\caption above \\begin{tabular} for tables.")
def table_caption_position(ctx):
    text = ctx.project.text
    for env in ctx.project.floats():
        if not env.name.startswith("table"):
            continue
        body = env.body(text)
        caps = parse_commands(body, "caption", 1)
        if not caps:
            continue
        tabular = re.search(r"\\begin\s*\{(?:tabular|tabularx|longtable|tabu)", body)
        if not tabular:
            continue
        if caps[0].start < tabular.start():
            continue
        offset = env.body_start + caps[0].start
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("FIG010", "table caption is below the table",
                          file=f, line=line, col=col, context=caps[0].arg(0)[:70],
                          fix="Move \\caption{...} (and its \\label) above \\begin{tabular}.")


@rule("FIG011", "Hard-coded float number in the text", Category.FLOATS, Severity.WARN,
      rationale="A written-out 'Figure 3' stops matching the moment a float is inserted before it.",
      fix="Replace with \\Cref{...} or \\ref{...}.")
def hardcoded_number(ctx):
    pattern = re.compile(
        r"\b(Figure|Fig\.|Table|Section|Sect\.|Chapter|Equation|Algorithm|Listing)\s*~?\s*(\d{1,2})(?![\d.])",
        re.IGNORECASE)
    for m in pattern.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("FIG011", f"hard-coded '{m.group(0).strip()}' instead of a cross-reference",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix="Use \\Cref{...} so the number follows the document.")
