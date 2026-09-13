"""Bibliography hygiene that needs no network.

Most of these exist because BibTeX exports are unreliable: the ACM DL, Google
Scholar and Zotero each drop or mangle different fields, and nobody notices
until the reference list is typeset.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from mechcheck import bibtex
from mechcheck.model import Category, Severity, rule

#: Fields a reader needs in order to find the work again.
REQUIRED = {
    "article": ["author", "title", "journal", "year"],
    "inproceedings": ["author", "title", "booktitle", "year"],
    "incollection": ["author", "title", "booktitle", "year"],
    "book": ["author", "title", "publisher", "year"],
    "inbook": ["author", "title", "publisher", "year"],
    "phdthesis": ["author", "title", "school", "year"],
    "mastersthesis": ["author", "title", "school", "year"],
    "techreport": ["author", "title", "institution", "year"],
    "misc": ["author", "title", "year"],
    "online": ["title", "url"],
    "www": ["title", "url"],
}

#: Words that must keep their capitals in a title, which BibTeX lower-cases
#: unless they are brace-protected.
PROPER_NOUNS = [
    "Android", "iOS", "Bayesian", "German", "English", "European", "American",
    "Likert", "Wizard of Oz", "Tesla", "Google", "Apple", "Microsoft", "Amazon",
    "Facebook", "Twitter", "YouTube", "Python", "Java", "LaTeX", "Overleaf",
    "COVID", "GDPR", "Internet", "Web", "Bluetooth", "WiFi", "Wi-Fi", "AI",
]


def entries(ctx) -> list:
    cached = ctx.cache.get("bib_entries")
    if cached is None:
        cached = bibtex.load_all(ctx.project.bib_files())
        ctx.cache["bib_entries"] = cached
    return cached


def _loc(ctx, entry, field: str | None = None) -> dict:
    return {
        "file": ctx.project.rel(entry.file),
        "line": entry.line_of(field) if field else entry.line,
    }


@rule("BIB001", "No bibliography file found", Category.BIB, Severity.WARN,
      rationale="Without a .bib the citation checks cannot run at all, so a missing file silently disables half the tool.",
      fix="Add \\bibliography{refs} (BibTeX) or \\addbibresource{refs.bib} (biblatex).")
def no_bib_file(ctx):
    if ctx.project.bib_files():
        return
    if not ctx.project.any_commands(["cite", "citep", "citet", "autocite", "parencite"], 1):
        return
    yield ctx.finding("BIB001", "the document cites work but no .bib file could be found",
                      file=ctx.project.main,
                      fix="Check the name in \\bibliography{...}/\\addbibresource{...} and that the file is committed.")


@rule("BIB002", "Entry missing a required field", Category.BIB, Severity.WARN,
      rationale="A reference without a venue or a year cannot be looked up, and the reference list prints a visible gap.",
      fix="Fill the field in from the publisher's page, not from memory.")
def missing_fields(ctx):
    for entry in entries(ctx):
        required = REQUIRED.get(entry.type)
        if not required:
            continue
        missing = [f for f in required if not entry.get(f).strip()]
        # biblatex accepts date instead of year, and journaltitle instead of journal.
        if "year" in missing and entry.get("date"):
            missing.remove("year")
        if "journal" in missing and entry.get("journaltitle"):
            missing.remove("journal")
        if not missing:
            continue
        yield ctx.finding("BIB002",
                          f"@{entry.type}{{{entry.key}}} is missing: {', '.join(missing)}",
                          context=entry.title[:70], **_loc(ctx, entry),
                          fix=f"Add {', '.join(missing)} to this entry.",
                          data={"key": entry.key, "missing": missing})


@rule("BIB003", "Duplicate bibliography entry", Category.BIB, Severity.WARN,
      rationale="The same work under two keys cites inconsistently and inflates the reference count.",
      fix="Keep one entry and update the citations that used the other key.")
def duplicates(ctx):
    by_doi = defaultdict(list)
    by_title = defaultdict(list)
    for entry in entries(ctx):
        if entry.doi:
            by_doi[entry.doi.lower()].append(entry)
        title = bibtex.normalise_title(entry.title)
        if len(title) > 15:
            by_title[title].append(entry)

    reported = set()
    for group in list(by_doi.values()) + list(by_title.values()):
        if len(group) < 2:
            continue
        keys = tuple(sorted(e.key for e in group))
        if keys in reported:
            continue
        reported.add(keys)
        first = group[0]
        for entry in group[1:]:
            yield ctx.finding("BIB003",
                              f"`{entry.key}` duplicates `{first.key}` ({first.file and ''}line {first.line})",
                              context=entry.title[:70], **_loc(ctx, entry),
                              fix=f"Delete one and point all citations at the survivor.",
                              data={"key": entry.key, "duplicate_of": first.key})


@rule("BIB004", "Preprint cited where a published version may exist", Category.BIB, Severity.INFO,
      rationale="Citing the arXiv version of a paper that appeared at CHI three years ago reads as not having followed the literature.",
      fix="Check for the published version and cite that; keep the preprint only if there is none.")
def preprint_citation(ctx):
    for entry in entries(ctx):
        if not entry.is_preprint():
            continue
        year = entry.year
        # A preprint from this year or last is fine; older ones deserve a look.
        threshold = int(ctx.opt("BIB004", "grace_years", 2) or 2)
        current = int(ctx.opt("BIB004", "current_year", 0) or date.today().year)
        if current and year and (current - year) < threshold:
            continue
        yield ctx.finding("BIB004", f"`{entry.key}` cites a preprint ({year or 'no year'})",
                          context=entry.title[:70], **_loc(ctx, entry),
                          data={"key": entry.key})


@rule("BIB005", "Unprotected proper noun in a title", Category.BIB, Severity.INFO,
      rationale="BibTeX lower-cases titles for most styles, so 'German' silently prints as 'german'.",
      fix="Brace the word: {German}.")
def unprotected_capitals(ctx):
    for entry in entries(ctx):
        raw_title = entry.get("title")
        if not raw_title:
            continue
        for word in PROPER_NOUNS:
            for m in re.finditer(rf"(?<![\w{{]){re.escape(word)}(?![\w}}])", raw_title):
                # Already inside braces?
                before = raw_title[:m.start()]
                if before.count("{") > before.count("}"):
                    continue
                yield ctx.finding("BIB005",
                                  f"`{entry.key}`: '{word}' in the title is not brace-protected",
                                  context=raw_title[:70], **_loc(ctx, entry, "title"),
                                  fix=f"Write {{{word}}} so the capital survives.",
                                  data={"key": entry.key, "word": word})
                break


@rule("BIB006", "'et al.' inside an author field", Category.BIB, Severity.ERROR,
      rationale="BibTeX reads 'et al.' as a person's name and prints it as an author; the abbreviation is the style's job, not yours.",
      fix="List every author, separated by ' and '. Use 'and others' if you truly must truncate.")
def et_al_in_authors(ctx):
    for entry in entries(ctx):
        raw = entry.get("author") or entry.get("editor")
        if not raw:
            continue
        if re.search(r"\bet\.?\s*al\.?", raw, re.IGNORECASE):
            yield ctx.finding("BIB006", f"`{entry.key}` has 'et al.' in the author field",
                              context=raw[:70], **_loc(ctx, entry, "author"),
                              fix="Replace with the full author list, or with 'and others'.",
                              data={"key": entry.key})


@rule("BIB007", "Authors separated by commas instead of 'and'", Category.BIB, Severity.ERROR,
      rationale="BibTeX splits authors on ' and '; a comma-separated list collapses into one enormous surname.",
      fix="Separate every author with ' and '.")
def comma_separated_authors(ctx):
    for entry in entries(ctx):
        raw = entry.get("author")
        if not raw or re.search(r"\sand\s", raw, re.IGNORECASE):
            continue
        # "Surname, Firstname" is one author and perfectly fine.
        if raw.count(",") >= 2:
            yield ctx.finding("BIB007",
                              f"`{entry.key}` looks like a comma-separated author list",
                              context=raw[:70], **_loc(ctx, entry, "author"),
                              fix="Use ' and ' between authors: Doe, Jane and Roe, Rick.",
                              data={"key": entry.key})


@rule("BIB008", "Page range with a single hyphen", Category.BIB, Severity.INFO,
      rationale="Page ranges take an en dash; BibTeX writes it as --.",
      fix="Write pages = {101--110}.")
def page_range(ctx):
    for entry in entries(ctx):
        pages = entry.get("pages")
        if not pages or "--" in pages:
            continue
        if re.match(r"^\s*\d+\s*-\s*\d+\s*$", pages):
            suggestion = re.sub(r"\s*-\s*", "--", pages.strip())
            yield ctx.finding("BIB008", f"`{entry.key}` has pages = {{{pages}}}",
                              context=pages, **_loc(ctx, entry, "pages"),
                              fix=f"Write pages = {{{suggestion}}}.",
                              data={"key": entry.key})


@rule("BIB009", "Missing DOI", Category.BIB, Severity.INFO,
      rationale="The ACM Reference Format expects a DOI; without one the reference cannot be resolved automatically and the online checks cannot verify it either.",
      fix="Copy the DOI from the publisher's page into doi = {10.1145/...}.")
def missing_doi(ctx):
    for entry in entries(ctx):
        if entry.doi or entry.type in ("misc", "online", "www", "unpublished", "booklet"):
            continue
        if entry.is_preprint():
            continue
        yield ctx.finding("BIB009", f"`{entry.key}` has no DOI",
                          context=entry.title[:70], **_loc(ctx, entry),
                          data={"key": entry.key})


@rule("BIB010", "URL cited without an access date", Category.BIB, Severity.INFO,
      rationale="A web source with no access date cannot be checked by a reader later, and most thesis regulations require one.",
      fix="Add urldate = {2026-08-27} (biblatex) or note = {Accessed: 2026-08-27}.")
def url_without_date(ctx):
    for entry in entries(ctx):
        if not entry.get("url"):
            continue
        if entry.doi:
            continue
        if entry.get("urldate") or re.search(r"accessed|retrieved|abgerufen|zugriff",
                                             entry.get("note"), re.IGNORECASE):
            continue
        yield ctx.finding("BIB010", f"`{entry.key}` cites a URL with no access date",
                          context=entry.get("url")[:70], **_loc(ctx, entry, "url"),
                          data={"key": entry.key})


@rule("BIB011", "Inconsistent venue name for the same conference", Category.BIB, Severity.INFO,
      rationale="'Proc. of CHI', 'CHI '24' and the full ACM name in one bibliography print as three different venues.",
      fix="Normalise the booktitle across entries -- bibtex-tidy or a shared string does this well.")
def inconsistent_venues(ctx):
    acronyms = defaultdict(set)
    for entry in entries(ctx):
        venue = entry.venue
        if not venue:
            continue
        for acronym in re.findall(r"\b(CHI|UIST|CSCW|IMWUT|UbiComp|AutomotiveUI|AutoUI|ASSETS|MobileHCI|IUI|DIS|TEI|ICMI)\b",
                                  venue, re.IGNORECASE):
            acronyms[acronym.upper()].add(re.sub(r"\s+", " ", venue.strip()))
    for acronym, variants in acronyms.items():
        if len(variants) < 2:
            continue
        listed = sorted(variants)[:3]
        yield ctx.finding("BIB011",
                          f"{acronym} appears under {len(variants)} different venue names",
                          context=" | ".join(v[:40] for v in listed),
                          file=ctx.project.rel(entries(ctx)[0].file) if entries(ctx) else None,
                          fix="Pick one form and use it for every entry of this venue.")


@rule("BIB012", "Bibliography entry with a suspicious year", Category.BIB, Severity.WARN,
      rationale="A year in the future or before 1900 is a typo, and typos in years are how a citation becomes unfindable.",
      fix="Correct the year.")
def suspicious_year(ctx):
    current = int(ctx.opt("BIB012", "current_year", 0) or date.today().year)
    for entry in entries(ctx):
        year = entry.year
        if year is None:
            continue
        if year < 1900 or (current and year > current + 1):
            yield ctx.finding("BIB012", f"`{entry.key}` has year = {year}",
                              context=entry.title[:70], **_loc(ctx, entry, "year"),
                              data={"key": entry.key})


_BOOKTITLE_IN = re.compile(
    r"^\s*\{?\s*In[:\s]\s*(?:Proceedings|Proc\b\.?|Companion|Adjunct|Extended|Conference|"
    r"International|Workshop|Symposium|the\b|\d|[A-Z]{2,})")


@rule("BIB013", "Booktitle begins with 'In'", Category.BIB, Severity.WARN,
      rationale="Every bibliography style writes 'In' before the booktitle itself, so an entry that already starts with it prints 'In In Proceedings of ...'. Google Scholar exports arrive this way.",
      fix="Delete the leading 'In' from the booktitle.")
def booktitle_starts_with_in(ctx):
    for entry in entries(ctx):
        booktitle = entry.get("booktitle")
        if not booktitle or not _BOOKTITLE_IN.match(booktitle):
            continue
        yield ctx.finding("BIB013", f"`{entry.key}`: the booktitle starts with 'In', which the style adds itself",
                          context=booktitle[:70], **_loc(ctx, entry, "booktitle"),
                          data={"key": entry.key})


@rule("BIB014", "Title written in capitals", Category.BIB, Severity.INFO,
      rationale="A title typed in capitals prints in capitals: most styles do not lower-case what they are given, so the entry shouts from the reference list.",
      fix="Retype the title in ordinary case and let the bibliography style decide the capitalisation.")
def shouting_title(ctx):
    for entry in entries(ctx):
        words = re.findall(r"[A-Za-z]{2,}", entry.title)
        if len(words) < 4:
            continue
        capitals = sum(1 for w in words if w.isupper())
        if capitals < 0.8 * len(words):
            continue
        yield ctx.finding("BIB014", f"`{entry.key}`: the title is written in capitals",
                          context=entry.title[:70], **_loc(ctx, entry, "title"),
                          data={"key": entry.key})


@rule("BIB015", "URL field repeats the DOI", Category.BIB, Severity.INFO,
      rationale="The ACM Reference Format prints the DOI as a link and then the url field as another, so a url of https://doi.org/... prints the same address twice.",
      fix="Delete the url field; the doi field carries the link.")
def url_duplicates_doi(ctx):
    for entry in entries(ctx):
        url = entry.get("url")
        if not url or not entry.get("doi").strip():
            continue
        if not re.search(r"doi\.org/", url, re.IGNORECASE):
            continue
        yield ctx.finding("BIB015", f"`{entry.key}` has both a doi and a url that points at doi.org",
                          context=url[:70], **_loc(ctx, entry, "url"),
                          data={"key": entry.key})


@rule("BIB016", "Title ends with a period", Category.BIB, Severity.INFO,
      rationale="The style puts its own period after the title, so one typed into the field prints as two.",
      fix="Remove the trailing period from the title field.")
def title_trailing_period(ctx):
    for entry in entries(ctx):
        raw = re.sub(r"[\s}]+$", "", entry.get("title"))
        if not raw.endswith(".") or raw.endswith(("...", "etc.", "al.")):
            continue
        if re.search(r"(?<![\w])[A-Za-z]\.$", raw):
            continue  # an initial or a roman numeral, not a stray period
        yield ctx.finding("BIB016", f"`{entry.key}`: the title ends with a period",
                          context=entry.title[:70], **_loc(ctx, entry, "title"),
                          data={"key": entry.key})


@rule("BIB017", "Duplicate citation key", Category.BIB, Severity.ERROR,
      rationale="BibTeX stops with 'Repeated entry' and biber silently keeps one of the two; either way, half the citations point at an entry the author did not intend.",
      fix="Rename or delete one of the two entries and update its citations.")
def duplicate_keys(ctx):
    seen: dict = {}
    for entry in entries(ctx):
        key = entry.key.strip().lower()   # BibTeX compares keys case-insensitively
        if not key:
            continue
        if key in seen:
            first = seen[key]
            yield ctx.finding("BIB017",
                              f"`{entry.key}` is defined twice (first at {ctx.project.rel(first.file)}:{first.line})",
                              context=entry.title[:70], **_loc(ctx, entry),
                              data={"key": entry.key})
            continue
        seen[key] = entry
