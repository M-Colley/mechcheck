"""Source-level writing mechanics.

Everything here is decidable from the characters on the page.  Anything that
needs an opinion about the argument belongs in a supervision meeting, not in a
linter -- that boundary is what makes the tool trustworthy enough to be
mandatory.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule

_TODO = re.compile(r"(?<![\w])(TODO|FIXME|XXX|TBD|HACK|REWRITE|CITATION NEEDED|\?\?\?)(?![\w])",
                   re.IGNORECASE)

_DOUBLE_WORD = re.compile(r"(?<![\w])([A-Za-z]{2,})\s+\1(?![\w])", re.IGNORECASE)

#: Words that legitimately repeat.
_DOUBLE_OK = {"had", "that", "long", "sehr"}

_US_UK = [
    ("behavior", "behaviour"), ("color", "colour"), ("modeling", "modelling"),
    ("analyze", "analyse"), ("organization", "organisation"), ("visualization", "visualisation"),
    ("center", "centre"), ("labeled", "labelled"), ("traveled", "travelled"),
    ("recognize", "recognise"), ("customization", "customisation"), ("defense", "defence"),
    ("fulfill", "fulfil"), ("judgment", "judgement"), ("license", "licence"),
]

_CONTRACTIONS = re.compile(
    r"(?<![\w])(don't|doesn't|didn't|can't|won't|isn't|aren't|wasn't|weren't|hasn't|haven't|"
    r"it's|we've|we're|they're|there's|that's|let's|couldn't|shouldn't|wouldn't)(?![\w])",
    re.IGNORECASE)


@rule("STY001", "Unfinished-work marker left in the text", Category.STYLE, Severity.ERROR,
      rationale="A TODO that reaches a supervisor or a reviewer costs more credibility than the missing content would have.",
      fix="Resolve it, or move it to your issue tracker.")
def todo_marker(ctx):
    for line in ctx.project.lines:
        for m in _TODO.finditer(line.raw):
            # A marker inside a comment is a private note; still worth flagging
            # before submission, but not while drafting.
            in_comment = "%" in line.raw[:m.start()] and not line.raw[:m.start()].rstrip().endswith("\\")
            severity = None
            if in_comment and ctx.config.stage == "draft":
                continue
            yield ctx.finding("STY001",
                              f"`{m.group(1)}` left in the source" + (" (in a comment)" if in_comment else ""),
                              file=line.file, line=line.lineno, col=m.start() + 1,
                              context=line.raw.strip()[:90],
                              severity=severity or ctx.config.severity_for("STY001"))


@rule("STY002", "Forced line break in running text", Category.STYLE, Severity.WARN,
      rationale=r"A \\ inside a paragraph breaks the line mid-sentence and leaves the previous line unjustified; it is almost always a leftover from editing.",
      fix=r"Delete the \\ and let LaTeX break the paragraph, or start a new paragraph with a blank line.")
def forced_linebreak_in_prose(ctx):
    text = ctx.project.text
    # Positions inside environments where \\ is the correct row separator.
    protected = []
    for env in ("tabular", "tabular*", "tabularx", "longtable", "tabu", "array", "matrix",
                "pmatrix", "bmatrix", "align", "align*", "gather", "gather*", "eqnarray",
                "eqnarray*", "cases", "split", "multline", "multline*", "flalign", "flalign*",
                "IEEEeqnarray", "tikzpicture", "verse", "addmargin", "titlepage", "center",
                "flushleft", "flushright", "minipage", "algorithmic", "lstlisting", "abstract"):
        for e in ctx.project.environments(env):
            protected.append((e.start, e.end))
    # Author blocks and title material legitimately use \\ too.
    for name in ("author", "title", "affiliation", "address", "date", "thanks", "makecell",
                 "shortstack", "parbox", "caption", "institute", "email"):
        for c in ctx.project.commands(name, 1):
            protected.append((c.start, c.end))

    def is_protected(pos: int) -> bool:
        return any(a <= pos <= b for a, b in protected)

    for m in re.finditer(r"\\\\(?![a-zA-Z])", text):
        if is_protected(m.start()):
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY002", "forced line break (\\\\) in running text",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix="Remove it; use a blank line if you want a new paragraph.")


@rule("STY003", "Repeated word", Category.STYLE, Severity.WARN,
      rationale="'the the' survives every spell-checker and every read-through, because the eye supplies the correct text.",
      fix="Delete the duplicate.")
def repeated_word(ctx):
    for m in _DOUBLE_WORD.finditer(ctx.project.prose):
        word = m.group(1).lower()
        if word in _DOUBLE_OK:
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY003", f"repeated word: '{m.group(0).strip()}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          edit=ctx.edit_span(m.start(), m.end(), m.group(1),
                                             f"{m.group(0)} -> {m.group(1)}"))


@rule("STY004", "Straight double quotes", Category.STYLE, Severity.INFO,
      rationale='A typed " renders as two identical marks; LaTeX needs ``opening and closing'' quotes.',
      fix="Use ``like this'' in English, or the csquotes package.")
def straight_quotes(ctx):
    if "csquotes" in ctx.project.packages():
        return
    for line in ctx.project.lines:
        if line.verbatim:
            continue
        for m in re.finditer(r'(?<![\\=])"', line.code):
            yield ctx.finding("STY004", "straight \" quote; LaTeX renders this as two closing marks",
                              file=line.file, line=line.lineno, col=m.start() + 1,
                              context=line.raw.strip()[:90],
                              fix="Write ``quoted text'' (two backticks, two apostrophes).")


@rule("STY005", "Space before punctuation", Category.STYLE, Severity.WARN,
      rationale="A space before a comma or full stop is a typing slip that survives into print.",
      fix="Delete the space.")
def space_before_punctuation(ctx):
    # Deliberately on the code view, not the prose view: prose masks commands to
    # spaces, so "\ref{x}." would look like " ." and every citation would fire.
    for line in ctx.project.lines:
        if line.verbatim:
            continue
        for m in re.finditer(r"(?<=[\w\)\}])[ \t]+([,.;:!?])(?=[ \t]|$)", line.code):
            start = line.offset + m.start()
            yield ctx.finding("STY005", f"space before '{m.group(1)}'",
                              file=line.file, line=line.lineno, col=m.start() + 1,
                              context=line.raw.strip()[:90],
                              edit=ctx.edit_span(start, line.offset + m.end(), m.group(1),
                                                 f"' {m.group(1)}' -> '{m.group(1)}'"))


@rule("STY006", "Citation glued to the preceding word", Category.STYLE, Severity.INFO,
      rationale="'shown in[12]' prints without a space; a tie keeps the citation attached but readable.",
      fix="Write word~\\cite{key}.")
def citation_spacing(ctx):
    for m in re.finditer(r"[A-Za-z0-9\)]\\(cite|citep|citet|autocite|parencite)\b", ctx.project.text):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY006", "no space or tie before the citation",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix="Insert ~ before \\cite.")


@rule("STY007", "Hyphen used for a numeric range", Category.STYLE, Severity.INFO,
      rationale="A range takes an en dash (--) in LaTeX; a single hyphen prints too short.",
      fix="Write 10--20.")
def numeric_range_hyphen(ctx):
    for m in re.finditer(r"(?<![\d\-])(\d{1,4})\s?-\s?(\d{1,4})(?![\d\-])", ctx.project.prose):
        a, b = int(m.group(1)), int(m.group(2))
        if b <= a:
            continue
        # "Core 7-1355" is a product number, not a range. Real ranges have
        # endpoints of comparable magnitude; a 1-digit to 4-digit jump does not.
        if len(m.group(2)) - len(m.group(1)) > 1:
            continue  # not a range: more likely a subtraction or an identifier
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY007", f"'{m.group(0)}' should use an en dash: {a}--{b}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          edit=ctx.edit_span(m.start(), m.end(), f"{a}--{b}",
                                             f"{m.group(0)} -> {a}--{b}"))


@rule("STY008", "Mixed British and American spelling", Category.STYLE, Severity.WARN,
      rationale="Reviewers read inconsistent spelling as carelessness; it is also the commonest artefact of text assembled from several sources.",
      fix="Pick one variety and apply it throughout.")
def mixed_spelling(ctx):
    prose = ctx.project.prose.lower()
    us_hits, uk_hits = [], []
    for us, uk in _US_UK:
        for m in re.finditer(rf"(?<![\w]){us}\w*", prose):
            us_hits.append((m.start(), m.group(0), uk))
        for m in re.finditer(rf"(?<![\w]){uk}\w*", prose):
            uk_hits.append((m.start(), m.group(0), us))
    if not us_hits or not uk_hits:
        return
    minority = us_hits if len(us_hits) <= len(uk_hits) else uk_hits
    majority_label = "British" if minority is us_hits else "American"
    for offset, word, alternative in minority[:12]:
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("STY008",
                          f"'{word}' is the minority spelling here; the document is mostly {majority_label}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                          fix=f"Use '{alternative}...' for consistency.")


@rule("STY009", "Contraction in formal writing", Category.STYLE, Severity.INFO,
      rationale="Contractions are out of register for a thesis or an ACM paper.",
      fix="Write the words out: don't -> do not.")
def contractions(ctx):
    for m in _CONTRACTIONS.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY009", f"contraction '{m.group(1)}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


@rule("STY010", "Inconsistent Figure/Fig. abbreviation", Category.STYLE, Severity.INFO,
      rationale="'Figure 1' in one paragraph and 'Fig. 1' in the next is the sort of inconsistency that makes a careful reader distrust the numbers too.",
      fix="Use one form; ACM style spells out 'Figure'.")
def figure_abbreviation(ctx):
    prose = ctx.project.prose
    long_form = [m.start() for m in re.finditer(r"(?<![\w])Figures?(?![\w])", prose)]
    short_form = [m.start() for m in re.finditer(r"(?<![\w])Figs?\.", prose)]
    if not long_form or not short_form:
        return
    minority = short_form if len(short_form) <= len(long_form) else long_form
    preferred = "Figure" if minority is short_form else "Fig."
    for offset in minority[:8]:
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("STY010",
                          f"mixed 'Figure'({len(long_form)}) and 'Fig.'({len(short_form)}) forms",
                          file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                          fix=f"Use '{preferred}' consistently.")


@rule("STY011", "Sentence-ending period after an abbreviation", Category.STYLE, Severity.INFO,
      rationale="'e.g. the' without a comma reads as a sentence break to LaTeX's spacing rules and prints a wide space.",
      fix="Write 'e.g.,' and 'i.e.,' -- or use \\eg macros.")
def eg_ie_comma(ctx):
    for m in re.finditer(r"(?<![\w])(e\.g\.|i\.e\.|cf\.|et al\.)(?![,)\\])\s", ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY011", f"'{m.group(1)}' is not followed by a comma",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=f"Write '{m.group(1)},' or add \\ after the period to fix the spacing.")


@rule("STY012", "Very long sentence", Category.STYLE, Severity.INFO,
      rationale="Sentences beyond roughly 45 words are where a second-language reader loses the thread; the count is objective even though the fix is editorial.",
      fix="Split it at the first 'and' or 'which'.")
def long_sentence(ctx):
    limit = int(ctx.opt("STY012", "max_words", 45) or 45)
    prose = ctx.project.prose
    for m in re.finditer(r"[^.!?]{40,}[.!?]", prose):
        chunk = m.group(0)
        words = [w for w in re.split(r"\s+", chunk.strip()) if w]
        if len(words) <= limit:
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY012", f"sentence of {len(words)} words (limit {limit})",
                          file=f, line=line, col=col,
                          context=" ".join(words[:12]) + " …")


@rule("STY013", "Paragraph break inside a sentence", Category.STYLE, Severity.WARN,
      rationale="A blank line ends the paragraph; when it lands mid-sentence the output silently splits in two.",
      fix="Remove the blank line, or finish the sentence.")
def paragraph_break_mid_sentence(ctx):
    lines = ctx.project.lines
    for i, line in enumerate(lines[:-1]):
        code = line.code.rstrip()
        if not code or line.verbatim:
            continue
        # Blank next line = paragraph break.
        nxt = lines[i + 1]
        if nxt.file != line.file or nxt.code.strip():
            continue
        stripped = code.rstrip()
        if stripped.endswith((".", "!", "?", ":", ";", "}", "]", "%", "\\", "-", ",")):
            continue
        if re.search(r"\\(item|end|begin|section|subsection|subsubsection|chapter|paragraph|caption|label|]|\))", stripped):
            continue
        if len(stripped) < 25 or not re.search(r"[a-z]\s*$", stripped):
            continue
        yield ctx.finding("STY013", "paragraph ends mid-sentence (blank line follows)",
                          file=line.file, line=line.lineno,
                          context=stripped[-70:],
                          fix="Delete the blank line, or complete the sentence.")


@rule("STY014", "Unescaped percent sign risk", Category.STYLE, Severity.INFO,
      rationale="A literal % comments out the rest of the line; the loss is silent and often only noticed in print.",
      fix="Write \\% for a percentage.")
def unescaped_percent(ctx):
    for line in ctx.project.lines:
        if line.verbatim:
            continue
        m = re.search(r"\d\s*%(?!\s*mechcheck)", line.raw)
        if not m:
            continue
        # If the % survived comment-stripping it was escaped; only flag the raw case.
        if len(line.code.rstrip()) > m.start():
            continue
        yield ctx.finding("STY014", "a number followed by an unescaped % -- the rest of the line is a comment",
                          file=line.file, line=line.lineno, col=m.start() + 1,
                          context=line.raw.strip()[:90], fix="Write \\%.")


#: A LaTeX control sequence starts with this. Named, so replacement strings
#: that must contain a backslash are built from something no escaping can eat.
BS = chr(92)

_ELLIPSIS = re.compile(r"(?<![.\\])\.\.\.(?!\.)")


@rule("STY015", "Three periods instead of an ellipsis", Category.STYLE, Severity.INFO,
      rationale="Typed periods are set too tightly and can break across a line; \\dots is the ellipsis LaTeX knows how to space.",
      fix="Write \\dots{} -- the empty braces keep the space that follows.")
def typed_ellipsis(ctx):
    for m in _ELLIPSIS.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY015", "'...' typed as three periods",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          edit=ctx.edit_span(m.start(), m.end(), BS + "dots{}",
                                             "... -> " + BS + "dots{}"))


_BARE_URL = re.compile(r"(?<![\w/@])(?:https?://|www\.)[^\s{}<>\"']+", re.IGNORECASE)

#: Commands whose arguments legitimately contain a URL as-is.
_URL_WRAPPERS = (("url", 1), ("href", 2), ("path", 1), ("nolinkurl", 1), ("hyperref", 2),
                 ("newcommand", 2), ("renewcommand", 2), ("providecommand", 2),
                 ("hypersetup", 1), ("includegraphics", 1), ("lstinputlisting", 1),
                 ("input", 1), ("include", 1), ("bibliography", 1), ("addbibresource", 1),
                 ("acmDOI", 1), ("doi", 1), ("Description", 1))


@rule("STY016", "Bare URL in running text", Category.STYLE, Severity.WARN,
      rationale="A URL typed as plain text cannot be broken across lines, so it runs into the margin, and its underscores, percent signs and tildes are read as LaTeX syntax rather than as characters.",
      fix="Wrap it: \\url{https://...}, from hyperref or the url package.")
def bare_url(ctx):
    text = ctx.project.text
    docs = ctx.project.environments("document")
    lo, hi = (docs[0].body_start, docs[0].body_end) if docs else (0, len(text))
    protected = []
    for name, nargs in _URL_WRAPPERS:
        for c in ctx.project.commands(name, nargs):
            protected.append((c.start, c.end))
    packages = ctx.project.packages()
    can_wrap = any(p in packages for p in ("hyperref", "url", "xurl"))
    for m in _BARE_URL.finditer(text, lo, hi):
        if any(a <= m.start() < b for a, b in protected):
            continue
        url = m.group(0).rstrip(".,;:)]")
        end = m.start() + len(url)
        shown = url if len(url) <= 48 else url[:47] + "\u2026"
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY016", f"bare URL: {shown}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=("Write " + BS + "url{" + shown + "}"
                               + ("" if can_wrap else ", and load hyperref (or url) in the preamble") + "."),
                          edit=(ctx.edit_span(m.start(), end, BS + "url{" + url + "}",
                                              "wrap in " + BS + "url{}") if can_wrap else None))


_SPACE_BEFORE_FOOTNOTE = re.compile(r"(?<=[^\s\\])(\s+)\\footnote(?![A-Za-z@])")


@rule("STY017", "Space before \\footnote", Category.STYLE, Severity.INFO,
      rationale="The footnote mark is set exactly where the command is, so a space before \\footnote prints a gap between the word and its superscript.",
      fix="Attach it directly to the word: word\\footnote{...}.")
def space_before_footnote(ctx):
    text = ctx.project.text
    for m in _SPACE_BEFORE_FOOTNOTE.finditer(text):
        f, line, col = ctx.project.locate(m.start(1))
        yield ctx.finding("STY017", "space between the word and its \\footnote",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          edit=ctx.edit_span(m.start(1), m.end(1), "",
                                             "delete the space before " + BS + "footnote"))


_NUMERAL_SENTENCE = re.compile(r"(?<![\w.,:;/\-])(\d[\d,.]*)\s+([a-z]{2,})")


@rule("STY018", "Sentence begins with a numeral", Category.STYLE, Severity.INFO,
      rationale="Style guides from APA to the ACM ask that a sentence not open with digits: '12 participants ...' reads as a fragment and is easily taken for a list item.",
      fix="Spell the number out ('Twelve participants ...') or rephrase ('A total of 12 participants ...').")
def numeral_starts_sentence(ctx):
    from mechcheck.texsource import sentence_starts_at

    prose = ctx.project.prose
    for m in _NUMERAL_SENTENCE.finditer(prose):
        if not sentence_starts_at(prose, m.start()):
            continue
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY018", f"sentence begins with '{m.group(1)}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


_LEGACY_FONT = re.compile(r"\\(bf|it|rm|sc|sf|tt|sl)(?![A-Za-z@])")
_DISPLAY_DOLLARS = re.compile(r"(?<!\\)\$\$")
_FONT_REPLACEMENT = {
    "bf": "\\textbf{...} or \\bfseries", "it": "\\textit{...}, \\emph{...} or \\itshape",
    "rm": "\\textrm{...} or \\rmfamily", "sc": "\\textsc{...} or \\scshape",
    "sf": "\\textsf{...} or \\sffamily", "tt": "\\texttt{...} or \\ttfamily",
    "sl": "\\textsl{...} or \\slshape",
}


@rule("STY019", "LaTeX 2.09 syntax", Category.STYLE, Severity.INFO,
      rationale="\\bf, \\it and $$ ... $$ predate LaTeX2e. The font commands do not nest and skip the italic correction, KOMA-Script and beamer refuse them, and $$ sets display maths with the wrong vertical space.",
      fix="Use \\textbf{...} and \\emph{...}, and \\[ ... \\] or an equation environment.")
def legacy_syntax(ctx):
    from mechcheck.texsource import _is_escaped

    text = ctx.project.text
    for m in _LEGACY_FONT.finditer(text):
        if _is_escaped(text, m.start()):
            continue
        name = m.group(1)
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY019", f"\\{name} is a LaTeX 2.09 font command",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix=f"Use {_FONT_REPLACEMENT[name]}.")
    opens = [m.start() for m in _DISPLAY_DOLLARS.finditer(text)]
    for start in opens[::2]:
        f, line, col = ctx.project.locate(start)
        yield ctx.finding("STY019", "$$ ... $$ display maths",
                          file=f, line=line, col=col, context=ctx.project.excerpt(start),
                          fix="Write \\[ ... \\] or an equation environment.")


_ET_AL = re.compile(r"(?<![\w])(?:et\.\s*al\.?|et\s+al(?![.\w])|etal\.?)(?![\w])")


_FILLER = re.compile(
    r"\blorem\s+ipsum\b|\bdolor\s+sit\s+amet\b|\btext\s+goes\s+here\b"
    r"|\b(?:figure|table|citation|reference)\s+(?:goes\s+)?here\b|\bplaceholder\s+text\b",
    re.IGNORECASE)

#: LaTeX prints an unresolved reference as "??" and an unresolved citation as
#: "[?]". Typed into the source they are a note to self that reads, in the
#: PDF, exactly like a broken build.
_UNRESOLVED_MARKER = re.compile(r"(?<![\w?])\?\?(?!\?)|(?<![\w])\[\s*\?\s*\]")


@rule("STY021", "Filler text or an unresolved-reference marker", Category.STYLE, Severity.WARN,
      rationale="'lorem ipsum' and a bare '??' reach a reviewer as an unfinished manuscript. The compile log reports '??' only once the document has been built twice, and nobody reads that log; typed into the source it is never reported at all.",
      fix="Write the sentence, or resolve the cross-reference.")
def filler_text(ctx):
    prose = ctx.project.prose
    for m in _FILLER.finditer(prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY021", f"filler text: '{m.group(0)}'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))
    for m in _UNRESOLVED_MARKER.finditer(prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY021",
                          f"'{m.group(0)}' reads as an unresolved "
                          + ("reference" if "?" == m.group(0)[0] else "citation"),
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          fix="Point it at a real label or citation key.")


@rule("STY020", "'et al.' mistyped", Category.STYLE, Severity.WARN,
      rationale="'et al.' abbreviates 'et alii': no period after 'et', one after 'al'. The variants are the kind of slip a reviewer notices in the first paragraph and holds against the rest.",
      fix="Write 'et al.' -- or let \\citet{...} produce it.")
def malformed_et_al(ctx):
    for m in _ET_AL.finditer(ctx.project.prose):
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY020", f"'{m.group(0)}' should be 'et al.'",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()),
                          edit=ctx.edit_span(m.start(), m.end(), "et al.", f"{m.group(0)} -> et al."))
