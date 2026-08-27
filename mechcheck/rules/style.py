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
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


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
            yield ctx.finding("STY005", f"space before '{m.group(1)}'",
                              file=line.file, line=line.lineno, col=m.start() + 1,
                              context=line.raw.strip()[:90])


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
            continue  # not a range: more likely a subtraction or an identifier
        f, line, col = ctx.project.locate(m.start())
        yield ctx.finding("STY007", f"'{m.group(0)}' should use an en dash: {a}--{b}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(m.start()))


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
