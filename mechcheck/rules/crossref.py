"""Labels, references and citation keys.

These checks duplicate what LaTeX itself reports -- but only after a *second*
compile, buried in a log nobody reads.  Here they are found in the source, on
the first run, with the line number attached.
"""

from __future__ import annotations

import re
from collections import defaultdict

from mechcheck import bibtex
from mechcheck.model import Category, Severity, rule

REF_CMDS = ["ref", "cref", "Cref", "crefrange", "Crefrange", "autoref", "vref",
            "pageref", "nameref", "labelcref", "subref", "eqref"]
#: A LaTeX control sequence starts with this. Named rather than escaped inline,
#: because a regex matching backslashes is where escaping mistakes hide.
BS = chr(92)

CITE_CMDS = ["cite", "citep", "citet", "citeauthor", "citeyear", "citealp", "citealt",
             "citenum", "parencite", "textcite", "autocite", "footcite", "nocite",
             "citeA", "shortcite", "fullcite", "citeyearpar"]


#: Label prefixes REF002 never complains about.
_UNREFERENCED_LABEL_EXEMPT = {
    "fig", "figure", "tab", "table",          # FIG003 reports these better
    "sec", "subsec", "subsubsec", "section",  # labelled for optional reference
    "chap", "chapter", "part", "app", "appendix",
}


def _labels(ctx) -> dict:
    out = defaultdict(list)
    for cmd in ctx.project.commands("label", 1):
        key = cmd.arg(0).strip()
        if key:
            out[key].append(cmd.start)
    return out


def _refs(ctx) -> dict:
    out = defaultdict(list)
    for cmd in ctx.project.any_commands(REF_CMDS, 1):
        for key in cmd.arg(0).split(","):
            key = key.strip()
            if key:
                out[key].append(cmd.start)
    return out


def _cites(ctx) -> dict:
    out = defaultdict(list)
    for cmd in ctx.project.any_commands(CITE_CMDS, 1):
        for key in cmd.arg(0).split(","):
            key = key.strip()
            if key and "\\" not in key:
                out[key].append(cmd.start)
    return out


def _bib_keys(ctx) -> dict:
    cached = ctx.cache.get("bib_entries")
    if cached is None:
        cached = bibtex.load_all(ctx.project.bib_files())
        ctx.cache["bib_entries"] = cached
    return {e.key: e for e in cached}


@rule("REF001", "Reference to an undefined label", Category.CROSSREF, Severity.ERROR,
      rationale="An undefined reference prints as '??' in the PDF -- the most visible possible sloppiness.",
      fix="Fix the typo, or add the missing \\label.")
def undefined_reference(ctx):
    labels = _labels(ctx)
    for key, offsets in _refs(ctx).items():
        if key in labels or "\\" in key or "#" in key:
            continue
        for offset in offsets:
            f, line, col = ctx.project.locate(offset)
            near = _closest(key, labels.keys())
            hint = f" Did you mean `{near}`?" if near else ""
            yield ctx.finding("REF001", f"reference to undefined label `{key}`;{hint}".rstrip(";"),
                              file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                              fix=f"Define \\label{{{key}}} or correct the key.{hint}")


@rule("REF002", "Label never referenced", Category.CROSSREF, Severity.INFO,
      rationale="A label nothing points at is dead weight -- and often the sign of a cross-reference that was meant to exist.",
      fix="Reference it, or delete the label.")
def unreferenced_label(ctx):
    refs = _refs(ctx)
    for key, offsets in _labels(ctx).items():
        if key in refs:
            continue
        # Floats are covered more precisely by FIG003; avoid reporting twice.
        # Sectioning labels are exempt outright: authors label sections so a
        # cross-reference *can* be made, and most never are. That is not a defect.
        if key.split(":", 1)[0].lower() in _UNREFERENCED_LABEL_EXEMPT:
            continue
        offset = offsets[0]
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("REF002", f"label `{key}` is never referenced",
                          file=f, line=line, col=col, context=ctx.project.excerpt(offset))


@rule("REF003", "Duplicate label", Category.CROSSREF, Severity.ERROR,
      rationale="LaTeX keeps only the last definition, so every reference silently points at the wrong place.",
      fix="Rename one of them.")
def duplicate_label(ctx):
    for key, offsets in _labels(ctx).items():
        if len(offsets) < 2:
            continue
        first_f, first_line, _ = ctx.project.locate(offsets[0])
        for offset in offsets[1:]:
            f, line, col = ctx.project.locate(offset)
            yield ctx.finding("REF003",
                              f"label `{key}` is already defined at {first_f}:{first_line}",
                              file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                              fix="Rename one of the two labels.")


@rule("REF004", "Missing non-breaking space before a cross-reference", Category.CROSSREF, Severity.INFO,
      rationale="'Figure 7' must not break across a line; LaTeX only prevents that if you write the tie yourself.",
      fix="Write Figure~\\ref{...} with a tilde.")
def missing_tie(ctx):
    # REF008 covers the same text and gives better advice (drop the word and
    # use \autoref), so stand aside when it is enabled.
    if ctx.config.enabled("REF008"):
        return
    pattern = re.compile(
        r"\b(Figure|Fig\.|Table|Section|Sec\.|Chapter|Chap\.|Equation|Eq\.|Algorithm|Listing|Appendix)"
        r"([ ]+)\\(ref|cref|Cref|autoref|eqref|vref)\b")
    for m in pattern.finditer(ctx.project.text):
        f, line, col = ctx.project.locate(m.start(2))
        yield ctx.finding("REF004", f"use a non-breaking space: `{m.group(1)}~\\{m.group(3)}`",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=f"Replace the space with ~ : {m.group(1)}~\\{m.group(3)}{{...}}")


@rule("REF005", "Citation key not in the bibliography", Category.CROSSREF, Severity.ERROR,
      rationale="An unresolved citation prints as '[?]' and the entry is missing from the reference list.",
      fix="Add the entry to the .bib file, or fix the key.")
def undefined_citation(ctx):
    keys = _bib_keys(ctx)
    if not keys:
        return  # no .bib found: BIB001 reports that instead
    for key, offsets in _cites(ctx).items():
        if key in keys:
            continue
        for offset in offsets:
            f, line, col = ctx.project.locate(offset)
            near = _closest(key, keys.keys())
            hint = f" Did you mean `{near}`?" if near else ""
            yield ctx.finding("REF005", f"citation key `{key}` is not in the bibliography.{hint}",
                              file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                              fix=f"Add `{key}` to your .bib file, or correct the key.")


@rule("REF006", "Bibliography entry never cited", Category.CROSSREF, Severity.INFO,
      rationale="Uncited entries bloat a .bib and hide the ones that matter; with biblatex they can also leak into the printed list.",
      fix="Cite it or remove it -- keeping a personal 'to read' .bib separate works well.")
def uncited_entry(ctx):
    cites = _cites(ctx)
    entries = ctx.cache.get("bib_entries")
    if entries is None:
        entries = bibtex.load_all(ctx.project.bib_files())
        ctx.cache["bib_entries"] = entries
    if not entries:
        return
    if ctx.project.commands("nocite", 1):
        for cmd in ctx.project.commands("nocite", 1):
            if "*" in cmd.arg(0):
                return  # \nocite{*} prints everything on purpose
    for entry in entries:
        if entry.key in cites:
            continue
        yield ctx.finding("REF006", f"`{entry.key}` is in the bibliography but never cited",
                          file=ctx.project.rel(entry.file), line=entry.line,
                          context=entry.title[:70], data={"key": entry.key})


@rule("REF007", "Inconsistent cross-reference commands", Category.CROSSREF, Severity.INFO,
      rationale="Mixing \\ref, \\autoref and \\Cref produces 'Figure 1', 'figure 1' and '1' in the same document.",
      fix="Pick one (cleveref's \\Cref is the usual choice) and use it everywhere.")
def inconsistent_ref_style(ctx):
    counts = {}
    first = {}
    for name in ("ref", "autoref", "cref", "Cref"):
        cmds = ctx.project.commands(name, 1)
        if cmds:
            counts[name] = len(cmds)
            first[name] = cmds[0].start
    if len(counts) < 2:
        return
    dominant = max(counts, key=lambda k: counts[k])
    minority = {k: v for k, v in counts.items() if k != dominant}
    total_minor = sum(minority.values())
    if total_minor == 0 or total_minor > counts[dominant]:
        return  # genuinely mixed usage; not our call to make
    for name, count in minority.items():
        offset = first[name]
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("REF007",
                          f"document mostly uses \\{dominant} ({counts[dominant]}×) but \\{name} appears {count}×",
                          file=f, line=line, col=col,
                          fix=f"Convert the {count} \\{name} to \\{dominant}.")



#: Words a reference command can supply for itself.
_AUTOREF_WORDS = ("Figure", "Fig.", "Figures", "Table", "Tables", "Section", "Sec.",
                  "Sections", "Chapter", "Chap.", "Equation", "Eq.", "Algorithm",
                  "Listing", "Appendix", "Part", "Subsection")

_PREFIXED_REF = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(w) for w in _AUTOREF_WORDS) + r")"
    r"[ ~]+" + re.escape(BS) + r"(ref|cref|Cref|autoref)\b")

#: Capitalised words that are not surnames, so not a case for \citet.
_NOT_A_NAME = {
    "figure", "fig", "table", "section", "sec", "chapter", "equation", "eq",
    "algorithm", "listing", "appendix", "part", "the", "in", "see", "cf",
    "and", "for", "with", "this", "these", "those", "our", "we", "it", "as",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "acm", "ieee", "iso",
}

_NAME_BEFORE_CITE = re.compile(
    r"(?<![\w])(?P<name>[A-Z][A-Za-z'\u2019-]{1,})"
    r"(?P<rest>\s+et\s+al\.|\s+and\s+[A-Z][A-Za-z'\u2019-]{1,})?"
    r"[ ~]*" + re.escape(BS) + r"(?P<cmd>cite|citep|citealp)\b")


def _textual_cite_command(ctx) -> str:
    """Which textual-citation command this document actually has."""
    packages = ctx.project.packages()
    cls, _ = ctx.project.documentclass()
    if "biblatex" in packages:
        return BS + "textcite"
    if "natbib" in packages or cls.lower() == "acmart":
        return BS + "citet"
    return ""


@rule("REF008", "Prefixed cross-reference where \\autoref would do", Category.CROSSREF,
      Severity.WARN,
      rationale="Writing the word yourself means two places to keep in step, and it is the half that goes wrong: a table renumbered into a figure still reads 'Table'. \\autoref supplies the word from the label's own type.",
      fix="Replace Figure~\\ref{x} with \\autoref{x}.")
def prefer_autoref(ctx):
    from mechcheck.texsource import read_group, skip_space

    text = ctx.project.text
    for m in _PREFIXED_REF.finditer(text):
        word, cmd = m.group(1), m.group(2)
        f, line, col = ctx.project.locate(m.start())
        # The argument is needed to rewrite the whole invocation, not just the
        # command name: Figure~\ref{x} becomes \autoref{x}, braces included.
        group = read_group(text, skip_space(text, m.end()))
        key = group[0] if group else None
        arg_end = group[1] if group else m.end()
        if cmd in ("cref", "Cref"):
            # cleveref already prints the word, so this prints it twice.
            yield ctx.finding("REF008",
                              f"'{word}~\\{cmd}' prints the word twice — \\{cmd} supplies it already",
                              file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                              fix=f"Delete '{word}~' and keep \\{cmd}{{...}}.",
                              edit=ctx.edit_span(m.start(), m.start(2) - 1, "",
                                                 f"delete '{word}~'"))
        elif cmd == "autoref":
            yield ctx.finding("REF008",
                              f"'{word}~\\autoref' prints the word twice — \\autoref supplies it already",
                              file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                              fix=f"Delete '{word}~' and keep \\autoref{{...}}.",
                              edit=ctx.edit_span(m.start(), m.start(2) - 1, "",
                                                 f"delete '{word}~'"))
        else:
            yield ctx.finding("REF008",
                              f"write \\autoref instead of '{word}~\\ref'",
                              file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                              fix=f"Replace '{word}~\\ref{{x}}' with \\autoref{{x}}.",
                              edit=(ctx.edit_span(m.start(), arg_end,
                                                  BS + "autoref{" + key + "}",
                                                  f"{word}~{BS}ref{{{key}}} -> {BS}autoref{{{key}}}")
                                    if key else None))


@rule("REF009", "Author name written out before \\cite", Category.CROSSREF, Severity.WARN,
      rationale="'Colley et al. [12]' spells out a name the bibliography style can produce itself, so the two drift apart when the entry changes; a textual citation command keeps them in one place.",
      fix="Replace 'Name et al.~\\cite{key}' with \\citet{key} (natbib/acmart) or \\textcite{key} (biblatex).")
def prefer_citet(ctx):
    from mechcheck.texsource import read_group, skip_space

    command = _textual_cite_command(ctx)
    for m in _NAME_BEFORE_CITE.finditer(ctx.project.text):
        name = m.group("name")
        if name.lower() in _NOT_A_NAME:
            continue
        rest = (m.group("rest") or "").strip()
        cmd = m.group("cmd")
        # A bare surname immediately before a citation is the weakest signal;
        # require the "et al." or "and X" shape unless the option says otherwise.
        if not rest and not bool(ctx.opt("REF009", "include_single_names", False)):
            continue
        # ALL-CAPS before a citation is an acronym (VR, ANOVA, ADMS), never a surname.
        if name.isupper():
            continue
        shown = (name + " " + rest).strip()
        f, line, col = ctx.project.locate(m.start())
        group = read_group(ctx.project.text, skip_space(ctx.project.text, m.end()))
        key = group[0] if group else None
        arg_end = group[1] if group else m.end()
        if command:
            advice = f"Replace '{shown}~\\{cmd}{{key}}' with {command}{{key}}."
        else:
            advice = ("Load natbib (or biblatex) to get a textual citation command, "
                      "then replace this with \\citet{key}.")
        yield ctx.finding("REF009",
                          f"'{shown}~\\{cmd}' writes out a name the citation style can produce",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=advice, data={"name": name},
                          edit=(ctx.edit_span(m.start(), arg_end, f"{command}{{{key}}}",
                                              f"{shown}~{BS}{cmd}{{{key}}} -> {command}{{{key}}}")
                                if command and key else None))

def _closest(key: str, candidates, cutoff: float = 0.82):
    from difflib import get_close_matches

    hits = get_close_matches(key, list(candidates), n=1, cutoff=cutoff)
    return hits[0] if hits else None
