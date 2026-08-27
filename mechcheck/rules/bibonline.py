"""Verifying that the works you cite actually exist, and say what you claim.

This is the check that did not need to exist five years ago.  A bibliography
drafted with an LLM's help can contain entries that are plausible in every
respect -- real authors, a real venue, a title in the right style -- and simply
never happened.  A human reviewer cannot catch that; a DOI resolver can.

The design is conservative on purpose.  Accusing a student of fabricating a
reference is serious, so:

* a DOI that fails to resolve is reported as a *fact* ("this DOI does not
  resolve"), never as an accusation;
* a title mismatch is only raised when the similarity is far below anything a
  subtitle or a preprint-versus-published difference could explain;
* an entry the APIs simply do not know is INFO, not ERROR -- German-language
  theses, standards bodies and older workshop papers are genuinely missing from
  Crossref;
* every online rule is skipped entirely with ``--offline``, so CI without
  network access degrades instead of failing.
"""

from __future__ import annotations

from mechcheck import bibtex, net
from mechcheck.model import Category, Severity, rule
from mechcheck.rules.bib import entries

#: Below this, the title we cite and the title the DOI resolves to are not the
#: same work by any reasonable reading.
HARD_MISMATCH = 0.55
#: Between these two, worth a look but explainable (subtitle dropped, etc.).
SOFT_MISMATCH = 0.80


def _fetcher(ctx) -> net.Fetcher:
    fetcher = ctx.cache.get("fetcher")
    if fetcher is None:
        mailto = ctx.opt("BIO001", "mailto", None) or ctx.config.data.get("mailto")
        fetcher = net.Fetcher(mailto=mailto, offline=ctx.offline)
        ctx.cache["fetcher"] = fetcher
    return fetcher


def _resolved(ctx) -> dict:
    """DOI -> Crossref work (or None if it does not resolve). Cached per run."""
    cache = ctx.cache.setdefault("crossref_by_doi", {})
    fetcher = _fetcher(ctx)
    for entry in entries(ctx):
        doi = entry.doi
        if doi and doi not in cache:
            cache[doi] = net.crossref_by_doi(fetcher, doi)
    return cache


def _work_title(work) -> str:
    if not work:
        return ""
    title = work.get("title")
    if isinstance(title, list):
        return title[0] if title else ""
    return title or ""


def _work_year(work):
    if not work:
        return None
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((work.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            return int(parts[0])
    return None


def _work_surnames(work) -> list:
    out = []
    for author in (work or {}).get("author") or []:
        family = author.get("family")
        if family:
            out.append(family)
    return out


@rule("BIO001", "DOI does not resolve", Category.BIB_ONLINE, Severity.ERROR, online=True,
      rationale="A DOI that Crossref does not know is either mistyped or points at a work that does not exist. Both must be fixed before submission.",
      fix="Open https://doi.org/<the DOI> yourself. If it 404s, find the real DOI on the publisher's page.")
def unresolvable_doi(ctx):
    resolved = _resolved(ctx)
    fetcher = _fetcher(ctx)
    for entry in entries(ctx):
        doi = entry.doi
        if not doi:
            continue
        if resolved.get(doi) is not None:
            continue
        # Crossref does not mint every DOI: DataCite, medRxiv and some
        # publishers live elsewhere. Ask OpenAlex before calling it broken.
        if net.openalex_by_doi(fetcher, doi):
            continue
        yield ctx.finding("BIO001", f"`{entry.key}`: DOI {doi} does not resolve",
                          file=ctx.project.rel(entry.file), line=entry.line_of("doi"),
                          context=entry.title[:70],
                          fix=f"Check https://doi.org/{doi} — if it fails, replace the DOI.",
                          data={"key": entry.key, "doi": doi})


@rule("BIO002", "Cited title does not match the DOI", Category.BIB_ONLINE, Severity.ERROR, online=True,
      rationale="If the DOI resolves to a different paper, the citation sends the reader to the wrong work -- and every claim attributed to it is unsupported.",
      fix="Replace either the DOI or the title so the entry describes one real work.")
def doi_title_mismatch(ctx):
    resolved = _resolved(ctx)
    for entry in entries(ctx):
        work = resolved.get(entry.doi)
        if not work or not entry.title:
            continue
        actual = _work_title(work)
        score = bibtex.similarity(entry.title, actual)
        if score >= SOFT_MISMATCH:
            continue
        severity = None if score < HARD_MISMATCH else Severity.WARN
        yield ctx.finding("BIO002",
                          f"`{entry.key}`: the DOI resolves to \"{bibtex.clean_latex(actual)[:80]}\" "
                          f"(similarity {score:.2f})",
                          file=ctx.project.rel(entry.file), line=entry.line_of("title"),
                          context=entry.title[:70],
                          severity=severity or ctx.config.severity_for("BIO002"),
                          fix="Correct the title, or point the entry at the right DOI.",
                          data={"key": entry.key, "doi": entry.doi,
                                "resolved_title": actual, "similarity": score})


@rule("BIO003", "Year disagrees with the record", Category.BIB_ONLINE, Severity.WARN, online=True,
      rationale="A wrong year misleads the reader about how current the work is, and breaks author-year citations.",
      fix="Use the year of the version you actually cite.")
def year_mismatch(ctx):
    resolved = _resolved(ctx)
    for entry in entries(ctx):
        work = resolved.get(entry.doi)
        if not work:
            continue
        cited, actual = entry.year, _work_year(work)
        if not cited or not actual or abs(cited - actual) <= 1:
            continue  # online-first publication legitimately straddles a year
        yield ctx.finding("BIO003",
                          f"`{entry.key}`: cited as {cited}, the DOI record says {actual}",
                          file=ctx.project.rel(entry.file), line=entry.line_of("year"),
                          context=entry.title[:70],
                          fix=f"Change year to {actual}.",
                          data={"key": entry.key, "cited": cited, "actual": actual})


@rule("BIO004", "Authors disagree with the record", Category.BIB_ONLINE, Severity.WARN, online=True,
      rationale="Wrong authorship is a citation error that propagates: the next person to cite you copies it.",
      fix="Take the author list from the publisher's page.")
def author_mismatch(ctx):
    resolved = _resolved(ctx)
    for entry in entries(ctx):
        work = resolved.get(entry.doi)
        if not work:
            continue
        cited = {s.lower() for s in entry.author_surnames()}
        actual = {s.lower() for s in _work_surnames(work)}
        if not cited or not actual:
            continue
        overlap = len(cited & actual) / max(1, min(len(cited), len(actual)))
        if overlap >= 0.5:
            continue
        yield ctx.finding("BIO004",
                          f"`{entry.key}`: cited authors {sorted(cited)[:3]} do not overlap "
                          f"the record's {sorted(actual)[:3]}",
                          file=ctx.project.rel(entry.file), line=entry.line_of("author"),
                          context=entry.title[:70],
                          data={"key": entry.key})


@rule("BIO005", "No record of this work anywhere", Category.BIB_ONLINE, Severity.WARN, online=True,
      rationale="An entry with no DOI that Crossref, OpenAlex and DBLP have all never heard of may not exist. This is how a fabricated reference looks.",
      fix="Verify the reference by hand. If it is real but simply unindexed (a German thesis, a standard, a technical report), add the URL and mark it: % mechcheck: off-file BIO005")
def unfindable_entry(ctx):
    fetcher = _fetcher(ctx)
    skip_types = {t.lower() for t in (ctx.opt("BIO005", "skip_types",
                                              ["online", "www", "misc", "unpublished", "techreport",
                                               "mastersthesis", "phdthesis", "manual", "booklet"]) or [])}
    for entry in entries(ctx):
        if entry.doi or entry.type in skip_types:
            continue
        title = entry.title
        if len(title) < 15:
            continue
        author = (entry.author_surnames() or [""])[0]

        best = 0.0
        best_title = ""
        for item in net.crossref_search(fetcher, title, author, rows=3):
            score = bibtex.similarity(title, _work_title(item))
            if score > best:
                best, best_title = score, _work_title(item)
        if best < SOFT_MISMATCH:
            for item in net.dblp_search(fetcher, title, rows=3):
                score = bibtex.similarity(title, item.get("title", ""))
                if score > best:
                    best, best_title = score, item.get("title", "")
        if best < SOFT_MISMATCH:
            for item in net.openalex_search(fetcher, title, rows=3):
                score = bibtex.similarity(title, item.get("title") or item.get("display_name") or "")
                if score > best:
                    best, best_title = score, item.get("display_name") or ""

        if best >= SOFT_MISMATCH:
            continue
        closest = f" Closest match: \"{best_title[:70]}\" ({best:.2f})." if best_title else ""
        yield ctx.finding("BIO005",
                          f"`{entry.key}` could not be found in Crossref, DBLP or OpenAlex.{closest}",
                          file=ctx.project.rel(entry.file), line=entry.line,
                          context=title[:70],
                          fix="Confirm this reference exists and add its DOI.",
                          data={"key": entry.key, "best_score": best, "best_title": best_title})


@rule("BIO006", "Cited work has been retracted", Category.BIB_ONLINE, Severity.ERROR, online=True,
      rationale="Citing retracted work without flagging it undermines the argument built on it, and reviewers increasingly check.",
      fix="Remove the citation, or cite it explicitly as retracted.")
def retracted(ctx):
    fetcher = _fetcher(ctx)
    resolved = _resolved(ctx)
    for entry in entries(ctx):
        doi = entry.doi
        if not doi:
            continue
        work = resolved.get(doi) or {}
        flagged = False
        reason = ""
        if str(work.get("type", "")).lower() == "retraction":
            flagged, reason = True, "Crossref type is 'retraction'"
        for update in work.get("update-to") or []:
            if str(update.get("type", "")).lower() in ("retraction", "withdrawal"):
                flagged, reason = True, "Crossref records a retraction notice"
        if not flagged:
            record = net.openalex_by_doi(fetcher, doi)
            if record and record.get("is_retracted"):
                flagged, reason = True, "OpenAlex marks this work as retracted"
        if not flagged:
            continue
        yield ctx.finding("BIO006", f"`{entry.key}` appears to be retracted ({reason})",
                          file=ctx.project.rel(entry.file), line=entry.line,
                          context=entry.title[:70],
                          data={"key": entry.key, "doi": doi})


@rule("BIO007", "Preprint now has a published version", Category.BIB_ONLINE, Severity.INFO, online=True,
      rationale="Citing the preprint of a paper that has since appeared is a small signal that the related work was assembled once and never revisited.",
      fix="Swap in the published version's entry.")
def preprint_superseded(ctx):
    fetcher = _fetcher(ctx)
    for entry in entries(ctx):
        if not entry.is_preprint() or not entry.title:
            continue
        for item in net.crossref_search(fetcher, entry.title,
                                        (entry.author_surnames() or [""])[0], rows=3):
            if str(item.get("type", "")).lower() in ("posted-content", "preprint"):
                continue
            if bibtex.similarity(entry.title, _work_title(item)) < 0.9:
                continue
            container = (item.get("container-title") or [""])[0]
            yield ctx.finding("BIO007",
                              f"`{entry.key}` is cited as a preprint but appears published"
                              + (f" in {container[:50]}" if container else ""),
                              file=ctx.project.rel(entry.file), line=entry.line,
                              context=entry.title[:70],
                              fix=f"Cite the published version (DOI {item.get('DOI')}).",
                              data={"key": entry.key, "published_doi": item.get("DOI")})
            break
