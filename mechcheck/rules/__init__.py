"""Importing this package registers every rule.

Rule id prefixes, one per module, so ids never collide:

    STR  structure.py      document skeleton
    FIG  floats.py         figures, tables, captions
    REF  crossref.py       labels, references, citations
    ABB  abbrev.py         abbreviations and acronyms
    TRM  terminology.py    one name per concept, one spelling per name
    STY  style.py          source-level writing mechanics
    BIB  bib.py            bibliography hygiene (offline)
    BIO  bibonline.py      bibliography verification (Crossref/OpenAlex/DBLP)
    LOG  compilelog.py     what the TeX log says
    MET  metrics.py        counts: words, pages, figures, references
    ANON anonymity.py      double-anonymous review sweep
    ACC  accessibility.py  alt text and accessible figures
    POL  policy.py         AI disclosure, ethics, open science, stats reporting
    VEN  venue.py          venue packs (CHI, ASSETS, AutoUI, IMWUT, TRF)
    THE  thesis.py         thesis-only formalities
    INT  runner.py         internal (a rule crashed)
"""

from mechcheck.rules import (  # noqa: F401
    abbrev,
    accessibility,
    anonymity,
    bib,
    bibonline,
    compilelog,
    crossref,
    floats,
    metrics,
    policy,
    structure,
    style,
    terminology,
    thesis,
    venue,
)
