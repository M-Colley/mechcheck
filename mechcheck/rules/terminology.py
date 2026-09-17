"""One name per concept, and one spelling for that name.

A reader who meets "self-driving car" on page 12 and "automated vehicle" on
page 13 has to decide whether they are the same thing. They usually are, and
the decision costs attention that belonged to the argument. Examiners notice
it, reviewers comment on it, and no spell-checker has ever caught it.

Everything here is decidable from the characters on the page, which keeps it
inside what this tool is allowed to have an opinion about:

* **What the document does** -- two names, two hyphenations or two
  capitalisations for one thing -- is a fact, so `TRM001`, `TRM003`, `TRM004`
  and `TRM005` report it and name the majority form without prescribing one.
  They are INFO: an author who deliberately distinguishes two similar terms
  is not making a mistake, and one comment silences the finding.
* **Which name to use** is a judgement, so `TRM002` fires only where somebody
  has written that judgement down. A group's house vocabulary goes in
  ``mechcheck.yaml``::

      terminology:
        - prefer: automated vehicle
          over: [self-driving car, autonomous vehicle, driverless car]
        - variants: [participant, test person, test subject]

  ``prefer``/``over`` is prescriptive and carries an automatic fix, because
  the correction is then fully determined -- by the person who wrote the
  configuration, not by this file. ``variants`` only asks for consistency.

``mechcheck terms .`` prints the variants a document actually contains, as a
block ready to paste into that configuration, so a group can build its
vocabulary from a finished thesis rather than from memory.
"""

from __future__ import annotations

import re
from collections import defaultdict

from mechcheck.model import Category, Severity, rule

#: Groups shipped by default. Deliberately short: a synonym list is a claim
#: about a field, and the useful ones are local to a group. These are the
#: cases where the variants name one object and the choice between them is
#: house style rather than meaning. Anything contested belongs in a project's
#: own ``terminology:`` block, where the choice is visible and reviewable.
#:
#: A project's configured groups take precedence: a variant named there is
#: removed from the built-in group that also lists it.
DEFAULT_GROUPS: tuple = (
    # The popular-press names for one vehicle, plus the two terms the HCI
    # literature actually argues about. Authors who distinguish "automated"
    # from "autonomous" on purpose (by SAE level, say) will want to silence
    # this or configure their own group -- which is why it is INFO.
    ("automated vehicle", "autonomous vehicle", "self-driving car",
     "self-driving vehicle", "driverless car", "driverless vehicle",
     "autonomous car", "automated car", "robot car"),
    # "subject" alone is left out on purpose: "the subject of this thesis" is
    # not a person, and a rule cannot tell the two apart.
    ("participant", "test person", "test subject", "study participant"),
    ("mobile phone", "cell phone", "cellular phone"),
)


def _normalise(text: str) -> str:
    """Lowercase, hyphens and line breaks as single spaces."""
    return re.sub(r"[-\s]+", " ", text.strip().lower())


#: What may separate two words of one phrase: a hyphen, a space or two, or a
#: line wrap. Deliberately not "any whitespace": the prose view masks markup
#: to spaces, so an unbounded separator let "study" in one caption and
#: "Participant" in the next one six lines later match as "study participant".
_GAP = r"(?:-|[ \t]{1,2}|[ \t]*\n[ \t]*)"


def _variant_pattern(variant: str) -> str:
    r"""Match a phrase however it is hyphenated, and in the plural.

    ``self-driving car`` also matches ``self driving cars``: which of those
    the author wrote is `TRM003`'s business, not this rule's.
    """
    words = [re.escape(w) for w in re.split(r"[-\s]+", variant.strip()) if w]
    return _GAP.join(words) + r"(?:e?s)?"


def _compiled(variants) -> "re.Pattern":
    # Longest first: "self-driving vehicle" must win over "self-driving car"
    # where both could start at the same place, and alternation is greedy in
    # order, not by length.
    ordered = sorted(variants, key=len, reverse=True)
    body = "|".join(_variant_pattern(v) for v in ordered)
    return re.compile(r"(?<![\w-])(?:" + body + r")(?![\w-])", re.IGNORECASE)


def _configured(ctx) -> list:
    """The project's own groups, normalised into ``(variants, prefer)``."""
    out = []
    for entry in ctx.config.data.get("terminology") or []:
        if isinstance(entry, (list, tuple)):
            variants, prefer = [str(v) for v in entry], None
        elif isinstance(entry, dict):
            prefer = entry.get("prefer")
            prefer = str(prefer).strip() if prefer else None
            over = entry.get("over") or entry.get("variants") or []
            if isinstance(over, str):
                over = [over]
            variants = [str(v).strip() for v in over if str(v).strip()]
            if prefer and prefer not in variants:
                variants = [prefer] + variants
        else:
            continue
        variants = [v for v in variants if v]
        if len(variants) >= 2:
            out.append((tuple(variants), prefer))
    return out


def groups(ctx) -> list:
    """Every group in force: the project's, then what is left of the built-ins.

    A variant the project names is dropped from any built-in group that also
    lists it, so configuring one concept never leaves two rules arguing about
    the same words.
    """
    cached = ctx.cache.get("terminology_groups")
    if cached is not None:
        return cached
    configured = _configured(ctx)
    claimed = {_normalise(v) for variants, _p in configured for v in variants}
    out = list(configured)
    if ctx.opt("TRM001", "use_defaults", True):
        for variants in DEFAULT_GROUPS:
            kept = tuple(v for v in variants if _normalise(v) not in claimed)
            if len(kept) >= 2:
                out.append((kept, None))
    ctx.cache["terminology_groups"] = out
    return out


def occurrences(ctx) -> list:
    """For each group, ``{variant: [(start, end, text), ...]}`` from the prose."""
    cached = ctx.cache.get("terminology_hits")
    if cached is not None:
        return cached
    prose = ctx.project.prose
    out = []
    for variants, prefer in groups(ctx):
        by_variant: dict = {}
        canonical = {_normalise(v): v for v in variants}
        for m in _compiled(variants).finditer(prose):
            key = _normalise(m.group(0))
            # The match may be a plural: fall back to the singular spelling.
            name = canonical.get(key) or canonical.get(re.sub(r"e?s$", "", key))
            if not name:
                continue
            by_variant.setdefault(name, []).append((m.start(), m.end(), m.group(0)))
        out.append({"variants": variants, "prefer": prefer, "hits": by_variant})
    ctx.cache["terminology_hits"] = out
    return out


def _majority(hits: dict):
    """The most frequent variant, ties broken by which appears first."""
    return min(hits, key=lambda v: (-len(hits[v]), hits[v][0][0]))


@rule("TRM001", "Two names for one concept", Category.TERMINOLOGY, Severity.INFO,
      rationale="A reader who meets two names for one thing has to work out whether they are the same thing, and an examiner who decides they are not has found an inconsistency you did not intend.",
      fix="Pick one name and use it throughout. Writing it into mechcheck.yaml under `terminology: prefer/over` turns this into a checked -- and automatically corrected -- house rule.")
def mixed_terms(ctx):
    for group in occurrences(ctx):
        # A group with a preferred term is TRM002's: it can say which one is
        # wrong, and this rule cannot.
        if group["prefer"] or len(group["hits"]) < 2:
            continue
        hits = group["hits"]
        best = _majority(hits)
        for variant, found in sorted(hits.items(), key=lambda kv: kv[0]):
            if variant == best:
                continue
            for start, _end, text in found:
                f, line, col = ctx.project.locate(start)
                yield ctx.finding("TRM001",
                                  f"'{text}' and '{best}' are two names for one concept "
                                  f"({len(found)}x and {len(hits[best])}x)",
                                  file=f, line=line, col=col,
                                  context=ctx.project.excerpt(start),
                                  data={"used": variant, "majority": best})


def _recase(matched: str, replacement: str):
    """The replacement, wearing the capitalisation of what it replaces."""
    if matched.isupper() and len(matched) > 3:
        return None          # a shouted heading: not ours to guess at
    if matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _pluralise(matched: str, variant: str, replacement: str) -> str:
    """Carry a plural across: 'self-driving cars' -> 'automated vehicles'."""
    if _normalise(matched) != _normalise(variant) and _normalise(matched).endswith("s"):
        return replacement + "s"
    return replacement


#: Vowel letters that are pronounced as consonants, and consonants that are
#: not pronounced at all. The article follows the sound, and these are the
#: words where the sound and the spelling disagree.
_SOUNDS_CONSONANT = re.compile(r"^(?:uni|use|usu|usa|uti|ubi|eu|one|once|ewe)", re.IGNORECASE)
_SOUNDS_VOWEL = re.compile(r"^(?:hour|honest|hono|heir)", re.IGNORECASE)


def _article_for(phrase: str) -> str:
    """'a' or 'an', by the sound the phrase starts with."""
    if _SOUNDS_VOWEL.match(phrase):
        return "an"
    if _SOUNDS_CONSONANT.match(phrase):
        return "a"
    return "an" if phrase[:1].lower() in "aeiou" else "a"


def _carry_the_article(text: str, start: int, replacement: str):
    r"""Widen an edit to correct 'a'/'an' in front of it.

    Replacing "a self-driving car" with "automated vehicle" would leave "a
    automated vehicle": the article agrees with the word that follows it, and
    that word is about to change. Only a bare article separated by ordinary
    spaces is taken in -- anything else (``a \emph{self-driving car}``) is
    left alone rather than rewritten blind.
    """
    before = re.search(r"(?<![\w-])(a|an|A|An)([ \t]+)$", text[max(0, start - 24):start])
    if not before:
        return start, replacement
    wanted = _article_for(replacement)
    if wanted.lower() == before.group(1).lower():
        return start, replacement
    if before.group(1)[:1].isupper():
        wanted = wanted.capitalize()
    return start - len(before.group(0)), wanted + before.group(2) + replacement


@rule("TRM002", "Term is not the one this project uses", Category.TERMINOLOGY, Severity.WARN,
      rationale="Once a group has settled on a word, a document that uses a different one costs every later reader the same moment of doubt -- and unlike a house style nobody wrote down, this one is written down.",
      fix="Use the term named in mechcheck.yaml. `mechcheck fix .` makes the substitution for you.")
def wrong_term(ctx):
    for group in occurrences(ctx):
        prefer = group["prefer"]
        if not prefer:
            continue
        for variant, found in sorted(group["hits"].items(), key=lambda kv: kv[0]):
            if _normalise(variant) == _normalise(prefer):
                continue
            for start, end, text in found:
                replacement = _recase(text, _pluralise(text, variant, prefer))
                edit = None
                if replacement:
                    edit_start, widened = _carry_the_article(ctx.project.text, start, replacement)
                    edit = ctx.edit_span(edit_start, end, widened, f"{text} -> {replacement}")
                f, line, col = ctx.project.locate(start)
                yield ctx.finding("TRM002",
                                  f"'{text}' -- this project's term is '{prefer}'",
                                  file=f, line=line, col=col,
                                  context=ctx.project.excerpt(start),
                                  fix=f"Write '{replacement or prefer}'.",
                                  edit=edit,
                                  data={"used": variant, "preferred": prefer})


# --------------------------------------------------------------------------- #
# spelling one term two ways, found in the document itself
# --------------------------------------------------------------------------- #

_WORD = re.compile(r"(?<![\w-])([A-Za-z]{2,})(?![\w-])")
_HYPHENATED = re.compile(r"(?<![\w-])([A-Za-z]{3,})-([A-Za-z]{3,})(?![\w-])")


def _words(ctx) -> list:
    """Every plain word in the prose, as ``(start, end, text)``."""
    cached = ctx.cache.get("terminology_words")
    if cached is None:
        cached = [(m.start(1), m.end(1), m.group(1)) for m in _WORD.finditer(ctx.project.prose)]
        ctx.cache["terminology_words"] = cached
    return cached


def _attributive(prose: str, end: int) -> bool:
    """Is the compound used in front of a noun?

    English hyphenates a compound that modifies the following noun and leaves
    it open otherwise, so "a real-time system" and "runs in real time" are
    both correct. Only occurrences in the same position can be compared.
    """
    rest = prose[end:end + 40].lstrip(" \n")
    return bool(re.match(r"[A-Za-z]{2,}", rest))


@rule("TRM003", "One term spelled two ways", Category.TERMINOLOGY, Severity.INFO,
      rationale="'eye-tracking' and 'eye tracking' in one document is the commonest inconsistency in a thesis and the easiest to miss, because both readings are correct English and the eye supplies whichever it expects.",
      fix="Choose one spelling. Hyphenate it consistently, or close it up consistently.")
def mixed_hyphenation(ctx):
    prose = ctx.project.prose
    words = _words(ctx)
    lowered = [(s, e, t.lower()) for s, e, t in words]
    word_positions: dict = defaultdict(list)
    for start, end, text in lowered:
        word_positions[text].append((start, end))

    hyphenated: dict = defaultdict(list)
    for m in _HYPHENATED.finditer(prose):
        hyphenated[(m.group(1).lower(), m.group(2).lower())].append((m.start(), m.end()))

    # Adjacent words with nothing but an ordinary gap between them: the open
    # form. The gap is bounded for the same reason the phrase gap is -- masked
    # markup is spaces, and two words either side of it are not a compound.
    gap = re.compile(r"(?:[ \t]{1,2}|[ \t]*\n[ \t]*)\Z")
    open_form: dict = defaultdict(list)
    for (s1, e1, w1), (s2, e2, w2) in zip(lowered, lowered[1:]):
        if len(w1) < 3 or len(w2) < 3 or not gap.match(prose[e1:s2]):
            continue
        open_form[(w1, w2)].append((s1, e2))

    # Only pairs the document itself joins somewhere are candidates; every
    # other bigram in the text is just two words next to each other.
    candidates = set(hyphenated)
    for (w1, w2) in open_form:
        if w1 + w2 in word_positions:
            candidates.add((w1, w2))

    minimum = int(ctx.opt("TRM003", "min_occurrences", 1) or 1)
    for pair in sorted(candidates):
        closed = word_positions.get(pair[0] + pair[1], [])
        forms = {
            f"{pair[0]}-{pair[1]}": hyphenated.get(pair, []),
            f"{pair[0]} {pair[1]}": open_form.get(pair, []),
            pair[0] + pair[1]: closed,
        }
        present = {name: spots for name, spots in forms.items() if len(spots) >= minimum}
        if len(present) < 2:
            continue
        # Hyphen against open, with no closed form in play, is the one case
        # English grammar can explain. Compare only like positions.
        if not closed:
            hyphen_spots = [p for p in forms[f"{pair[0]}-{pair[1]}"] if _attributive(prose, p[1])]
            open_spots = [p for p in forms[f"{pair[0]} {pair[1]}"] if _attributive(prose, p[1])]
            if not hyphen_spots or not open_spots:
                continue
            present = {f"{pair[0]}-{pair[1]}": hyphen_spots, f"{pair[0]} {pair[1]}": open_spots}
        best = max(present, key=lambda name: (len(present[name]), -present[name][0][0]))
        tally = ", ".join(f"'{name}' ({len(spots)}x)" for name, spots in sorted(present.items()))
        for name, spots in sorted(present.items()):
            if name == best:
                continue
            start = spots[0][0]
            f, line, col = ctx.project.locate(start)
            yield ctx.finding("TRM003", f"one term, two spellings: {tally}",
                              file=f, line=line, col=col, context=ctx.project.excerpt(start),
                              fix=f"The document mostly writes '{best}'.",
                              data={"term": best, "variants": sorted(present)})
            break       # one finding per term, not one per spelling


_CAPITALISED = re.compile(r"(?<![\w-])([A-Z][a-z]{3,})(?![\w-])")
_LOWERCASE = re.compile(r"(?<![\w-])([a-z]{4,})(?![\w-])")


def _title_spans(ctx) -> list:
    """Headings, captions and titles, where Title Case is a convention."""
    cached = ctx.cache.get("terminology_title_spans")
    if cached is not None:
        return cached
    spans = []
    for name in ("section", "subsection", "subsubsection", "chapter", "part",
                 "paragraph", "title", "caption", "subcaption", "Description",
                 "keywords", "author", "institution", "affiliation"):
        for cmd in ctx.project.commands(name, 1):
            spans.append((cmd.start, cmd.end))
    ctx.cache["terminology_title_spans"] = spans
    return spans


def _in_capitalised_run(prose: str, start: int, end: int) -> bool:
    """Is this word one of several capitalised in a row?

    "Automated Driving System" is a name the author gave something, not three
    words whose capitalisation slipped, and its middle word must not be
    compared against the ordinary adjective "automated" elsewhere. A word that
    merely opens the sentence is no evidence of a run: it would be capitalised
    either way.
    """
    from mechcheck.texsource import sentence_starts_at

    window_at = max(0, start - 60)
    before = re.search(r"([A-Za-z][A-Za-z-]*)[ \t]+$", prose[window_at:start])
    if before and before.group(1)[:1].isupper():
        if not sentence_starts_at(prose, window_at + before.start(1)):
            return True
    after = re.match(r"[ \t]+([A-Za-z][A-Za-z-]*)", prose[end:end + 60])
    return bool(after and after.group(1)[:1].isupper())


@rule("TRM004", "One term, capitalised in some places and not others",
      Category.TERMINOLOGY, Severity.INFO,
      rationale="'the Participants completed' and 'the participants completed' in one document reads as two different decisions, and in a table of contents or a list of figures the inconsistency is on show.",
      fix="Capitalise a term mid-sentence only if it is a proper noun. Pick one and apply it throughout.")
def mixed_capitalisation(ctx):
    # German capitalises every noun, so the comparison means nothing there.
    if not ctx.config.language.lower().startswith("en"):
        return
    prose = ctx.project.prose
    titles = _title_spans(ctx)
    minimum = int(ctx.opt("TRM004", "min_occurrences", 2) or 2)

    def eligible(start: int) -> bool:
        from mechcheck.texsource import sentence_starts_at

        if any(a <= start < b for a, b in titles):
            return False
        return not sentence_starts_at(prose, start)

    upper: dict = defaultdict(list)
    for m in _CAPITALISED.finditer(prose):
        if eligible(m.start()) and not _in_capitalised_run(prose, m.start(), m.end()):
            upper[m.group(1).lower()].append(m.start())
    lower: dict = defaultdict(list)
    for m in _LOWERCASE.finditer(prose):
        if eligible(m.start()):
            lower[m.group(1)].append(m.start())

    for word in sorted(set(upper) & set(lower)):
        ups, lows = upper[word], lower[word]
        if len(ups) < minimum or len(lows) < minimum:
            continue
        minority, majority = (ups, "lower") if len(ups) <= len(lows) else (lows, "upper")
        shown = word.capitalize() if majority == "lower" else word
        want = word if majority == "lower" else word.capitalize()
        start = minority[0]
        f, line, col = ctx.project.locate(start)
        yield ctx.finding("TRM004",
                          f"'{shown}' is written both '{word}' ({len(lows)}x) and "
                          f"'{word.capitalize()}' ({len(ups)}x) mid-sentence",
                          file=f, line=line, col=col, context=ctx.project.excerpt(start),
                          fix=f"The document mostly writes '{want}'.",
                          data={"term": word})


@rule("TRM005", "Expansion still written out after the abbreviation was introduced",
      Category.TERMINOLOGY, Severity.INFO,
      rationale="Introducing an abbreviation is a promise to use it. Writing 'Automated Driving System' out a dozen more times makes the reader carry both forms and leaves the definition looking pointless.",
      fix="Use the abbreviation after the first definition, or drop the abbreviation and keep writing the term in full.")
def expansion_repeated(ctx):
    from mechcheck.rules.abbrev import _ACRONYM_USE, _definitions, _managed_by_package

    if _managed_by_package(ctx):
        return
    prose = ctx.project.prose
    threshold = int(ctx.opt("TRM005", "min_repeats", 3) or 3)
    acronym_uses: dict = defaultdict(list)
    for m in _ACRONYM_USE.finditer(prose):
        acronym_uses[m.group(1).upper()].append(m.start())

    for acronym, found in _definitions(ctx).items():
        defined_at = min(o[3] for o in found)       # end of the first definition
        expansion = found[0][1]
        if len(expansion) < 10:
            continue
        # An abbreviation nobody ever uses is ABB003's finding, not this one.
        if not any(pos > defined_at for pos in acronym_uses.get(acronym, [])):
            continue
        pattern = re.compile(r"(?<![\w-])" + _variant_pattern(expansion) + r"(?![\w-])",
                             re.IGNORECASE)
        repeats = []
        for m in pattern.finditer(prose, defined_at):
            # "Automated Driving System (ADS)" again is ABB001's territory.
            if re.match(r"\s*\(", prose[m.end():m.end() + 4]):
                continue
            repeats.append(m.start())
        if len(repeats) < threshold:
            continue
        start = repeats[0]
        f, line, col = ctx.project.locate(start)
        yield ctx.finding("TRM005",
                          f"'{expansion}' is written out {len(repeats)} more times after "
                          f"`{acronym}` was introduced",
                          file=f, line=line, col=col, context=ctx.project.excerpt(start),
                          fix=f"Write `{acronym}` from the definition onwards.",
                          data={"acronym": acronym, "expansion": expansion,
                                "repeats": len(repeats)})


# --------------------------------------------------------------------------- #
# `mechcheck terms`: the vocabulary a document actually contains
# --------------------------------------------------------------------------- #

def survey(ctx) -> dict:
    """What a document calls things, for ``mechcheck terms``.

    The point is adoption: a group writes its ``terminology:`` block by
    reading one finished thesis, not by trying to remember every word it
    argues about.
    """
    found = {"groups": [], "spellings": [], "capitalisation": []}
    for group in occurrences(ctx):
        if len(group["hits"]) < 2:
            continue
        found["groups"].append({
            "prefer": group["prefer"] or _majority(group["hits"]),
            "used": {v: len(spots) for v, spots in sorted(group["hits"].items())},
            "configured": bool(group["prefer"]),
        })
    for finding in mixed_hyphenation(ctx):
        found["spellings"].append(finding.data.get("variants", []))
    for finding in mixed_capitalisation(ctx):
        found["capitalisation"].append(finding.data.get("term"))
    return found


def render_survey(result) -> str:
    """The survey as text, ending in a block ready to paste into the config."""
    from mechcheck.model import RuleContext

    ctx = RuleContext(project=result.project, config=result.config,
                      root=result.project.root, offline=True)
    data = survey(ctx)
    out = [f"{result.project.main}: the terms this document uses more than one name for", ""]

    if not any(data.values()):
        out.append("  Nothing to report: every term this checker knows how to compare is")
        out.append("  used consistently.")
        return "\n".join(out)

    if data["groups"]:
        out.append("Two names for one concept")
        for entry in data["groups"]:
            tally = ", ".join(f"{name} ({n}x)" for name, n in entry["used"].items())
            mark = " [from your configuration]" if entry["configured"] else ""
            out.append(f"  {tally}{mark}")
        out.append("")
    if data["spellings"]:
        out.append("One term, two spellings")
        for variants in data["spellings"]:
            out.append("  " + " / ".join(variants))
        out.append("")
    if data["capitalisation"]:
        out.append("Capitalised in some places and not others")
        out.append("  " + ", ".join(data["capitalisation"]))
        out.append("")

    unconfigured = [e for e in data["groups"] if not e["configured"]]
    if unconfigured:
        out.append("To make one of these the project's term, put this in mechcheck.yaml")
        out.append("and mechcheck will check it -- and `mechcheck fix .` will apply it:")
        out.append("")
        out.append("terminology:")
        for entry in unconfigured:
            others = [name for name in entry["used"] if name != entry["prefer"]]
            out.append(f"  - prefer: {entry['prefer']}")
            out.append(f"    over: [{', '.join(others)}]")
    return "\n".join(out)
