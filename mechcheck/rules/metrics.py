"""Counts: words, pages, figures, references.

Length limits are the most mechanical requirement any venue has, and the one
most often discovered the night before a deadline.  Counting words the way a
venue counts them is not exact science -- ASSETS counts "words excluding
references", CHI talks about main text, AutoUI counts pages -- so each count
states what it included, and the venue packs say which count applies.
"""

from __future__ import annotations

import os
import re
import subprocess

from mechcheck.model import Category, Severity, rule
from mechcheck.rules.bib import entries

#: Sections whose whole purpose is to be short. Comparing them against the
#: median length of a Results section says nothing.
SHORT_BY_DESIGN = (
    "open science", "acknowledgment", "acknowledgement", "danksagung",
    "data availability", "availability statement", "declaration",
    "conflict of interest", "competing interest", "funding",
    "ethics", "ethical", "credit", "author contribution",
    "supplementary", "appendix", "abstract", "keywords",
    "ccs concepts", "disclosure", "preregistration", "artifact",
)

_STOP_COMMANDS = ("printbibliography", "bibliography", "printbibheading",
                  "begin{thebibliography}", "appendix")


def main_text_span(ctx):
    """Offsets of the body: after \\begin{document}, before the bibliography."""
    text = ctx.project.text
    start = 0
    docs = ctx.project.environments("document")
    if docs:
        start = docs[0].body_start
    end = len(text)
    for marker in _STOP_COMMANDS:
        m = re.search(r"\\" + re.escape(marker), text[start:])
        if m:
            end = min(end, start + m.start())
    return start, end


def word_count(ctx, include_floats: bool = False) -> int:
    """Words of running prose. Maths, markup and citations do not count."""
    cache_key = f"wordcount:{include_floats}"
    if cache_key in ctx.cache:
        return ctx.cache[cache_key]
    start, end = main_text_span(ctx)
    prose = list(ctx.project.prose[start:end])
    if not include_floats:
        for env in ctx.project.floats():
            a, b = env.start - start, env.end - start
            for i in range(max(0, a), min(len(prose), b)):
                prose[i] = " "
    words = [w for w in re.split(r"\s+", "".join(prose)) if len(w) > 1 or w.isalnum()]
    count = len([w for w in words if re.search(r"[A-Za-zÀ-ÿ]", w)])
    ctx.cache[cache_key] = count
    return count


def page_count(ctx):
    """Pages in the compiled PDF, or None when there is no build to look at."""
    if "pagecount" in ctx.cache:
        return ctx.cache["pagecount"]
    pages = None
    path = ctx.pdf_path
    if path and os.path.isfile(path):
        try:
            out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=20)
            m = re.search(r"^Pages:\s+(\d+)", out.stdout, re.MULTILINE)
            if m:
                pages = int(m.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
        if pages is None:
            pages = _pages_from_bytes(path)
    if pages is None and ctx.log_text:
        # latexmk/pdftex reports "Output written on x.pdf (12 pages, ...)".
        m = re.search(r"Output written on .*?\((\d+) pages?", ctx.log_text)
        if m:
            pages = int(m.group(1))
    ctx.cache["pagecount"] = pages
    return pages


def _pages_from_bytes(path: str):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", data)]
    if counts:
        return max(counts)
    hits = len(re.findall(rb"/Type\s*/Page[^s]", data))
    return hits or None


def _limit(ctx, rule_id: str, key: str, venue_path):
    value = ctx.opt(rule_id, key, None)
    if value is None:
        value = ctx.config.venue_field(*venue_path, default=None)
    try:
        return int(value) if value not in (None, "", False) else None
    except (TypeError, ValueError):
        return None


@rule("MET001", "Word count over the limit", Category.METRICS, Severity.WARN,
      rationale="Length limits are enforced by the submission system, not by the reviewers; discovering the overrun at the deadline costs a night.",
      fix="Cut, or check whether your venue counts references (most do not).")
def word_limit(ctx):
    maximum = _limit(ctx, "MET001", "max_words", ("length", "max_words"))
    minimum = _limit(ctx, "MET001", "min_words", ("length", "min_words"))
    if maximum is None and minimum is None:
        return
    count = word_count(ctx)
    where = ctx.project.main
    if maximum and count > maximum:
        yield ctx.finding("MET001",
                          f"{count} words of main text, limit {maximum} "
                          f"({count - maximum} over; references and floats excluded)",
                          file=where, fix=f"Remove about {count - maximum} words.",
                          data={"words": count, "limit": maximum})
    elif minimum and count < minimum:
        yield ctx.finding("MET001",
                          f"{count} words of main text, minimum {minimum}",
                          file=where, data={"words": count, "minimum": minimum})


@rule("MET002", "Page count outside the venue's range", Category.METRICS, Severity.ERROR,
      needs_build=True,
      rationale="Page limits are the single commonest desk-reject reason, and the only reliable count comes from the compiled PDF.",
      fix="Cut content, or move material to an appendix if the venue allows one.")
def page_limit(ctx):
    maximum = _limit(ctx, "MET002", "max_pages", ("length", "max_pages"))
    minimum = _limit(ctx, "MET002", "min_pages", ("length", "min_pages"))
    if maximum is None and minimum is None:
        return
    pages = page_count(ctx)
    if pages is None:
        return
    excludes = ctx.config.venue_field("length", "excludes", default="")
    note = f" ({excludes})" if excludes else ""
    if maximum and pages > maximum:
        yield ctx.finding("MET002", f"the PDF has {pages} pages, limit {maximum}{note}",
                          file=ctx.project.main,
                          fix=f"Remove {pages - maximum} page(s).",
                          data={"pages": pages, "limit": maximum})
    elif minimum and pages < minimum:
        yield ctx.finding("MET002", f"the PDF has {pages} pages, minimum {minimum}{note}",
                          file=ctx.project.main, data={"pages": pages, "minimum": minimum})


@rule("MET003", "Abstract length", Category.METRICS, Severity.INFO,
      rationale="An abstract far outside 150-250 words either omits the contribution or repeats the introduction.",
      fix="Aim for one sentence each: problem, approach, study, finding, implication.")
def abstract_length(ctx):
    envs = ctx.project.environments("abstract")
    if not envs:
        return
    low = int(ctx.opt("MET003", "min_words", 100) or 100)
    high = int(ctx.opt("MET003", "max_words", 300) or 300)
    env = envs[0]
    body = ctx.project.prose[env.body_start:env.body_end]
    count = len([w for w in re.split(r"\s+", body) if re.search(r"[A-Za-zÀ-ÿ]", w)])
    if low <= count <= high:
        return
    f, line, col = ctx.project.locate(env.start)
    yield ctx.finding("MET003", f"the abstract is {count} words (expected {low}-{high})",
                      file=f, line=line, col=col, data={"words": count})


@rule("MET004", "Very few references", Category.METRICS, Severity.INFO,
      rationale="A thin reference list is the first thing a reviewer counts; CHI-style venues expect the related work to be genuinely covered.",
      fix="Broaden the related work, or explain in the paper why the field is small.")
def reference_count(ctx):
    minimum = int(ctx.opt("MET004", "min_references", 0) or 0)
    if not minimum:
        return
    cited = set()
    for cmd in ctx.project.any_commands(["cite", "citep", "citet", "autocite", "parencite"], 1):
        for key in cmd.arg(0).split(","):
            if key.strip():
                cited.add(key.strip())
    if len(cited) >= minimum:
        return
    yield ctx.finding("MET004", f"only {len(cited)} distinct works are cited (expected at least {minimum})",
                      file=ctx.project.main, data={"cited": len(cited)})


@rule("MET005", "Section far longer or shorter than the rest", Category.METRICS, Severity.INFO,
      rationale="A 40-word section and a 4000-word one in the same document usually means the structure drifted from the plan.",
      fix="Merge the stub into its neighbour, or split the giant.")
def section_balance(ctx):
    sections = ctx.project.commands("section", 1)
    if len(sections) < 4:
        return
    start, end = main_text_span(ctx)
    bounds = []
    for i, sec in enumerate(sections):
        stop = sections[i + 1].start if i + 1 < len(sections) else end
        if sec.start >= end:
            continue
        body = ctx.project.prose[sec.start:stop]
        count = len([w for w in re.split(r"\s+", body) if re.search(r"[A-Za-zÀ-ÿ]", w)])
        bounds.append((sec, count))
    if len(bounds) < 4:
        return
    counts = sorted(c for _s, c in bounds)
    median = counts[len(counts) // 2]
    if median == 0:
        return
    for sec, count in bounds:
        if count >= max(60, median * 0.15):
            continue
        title = sec.arg(0).strip().lower()
        if any(marker in title for marker in SHORT_BY_DESIGN):
            continue   # these are meant to be short
        f, line, col = ctx.project.locate(sec.start)
        yield ctx.finding("MET005",
                          f"section \"{sec.arg(0)[:40]}\" has {count} words; the median section has {median}",
                          file=f, line=line, col=col,
                          fix="Expand it, merge it, or make it a subsection.")
