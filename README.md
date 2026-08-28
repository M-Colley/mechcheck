# mechcheck

[![self-test](https://github.com/M-Colley/mechcheck/actions/workflows/mechcheck.yml/badge.svg)](https://github.com/M-Colley/mechcheck/actions/workflows/mechcheck.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Mechanical checks for LaTeX theses and papers: the boring layer of review,
automated, so supervision time goes to the argument instead of the formatting.

117 rules across figures, cross-references, abbreviations, prose mechanics,
bibliography hygiene, **bibliography verification against Crossref/OpenAlex/DBLP**,
compile-log analysis, accessibility, anonymity, reporting conventions, and
per-venue submission requirements for CHI, ASSETS, AutomotiveUI, IMWUT and
Transportation Research Part F.

**Nothing to install.** Save
[`browser/mechcheck.html`](browser/mechcheck.html), double-click it, and drop
your Overleaf `.zip` on the page. Or load [`extension/`](extension/) in Chrome
and get a button inside Overleaf itself.

If you would rather have a command line:

```bash
pip install -e .
mechcheck check .                       # a thesis
mechcheck check . --venue chi           # + CHI's submission requirements
mechcheck check . --venue autoui --profile paper-anonymous --stage final
mechcheck fix .                         # apply the unambiguous corrections
```

---

## Four ways to run it

Overleaf's Git integration is premium and its GitHub sync is **manual** — there
is no webhook, so nothing can fire on a student's edit. That constraint produced
a layered design; use whichever layers suit you.

| | What | Runs | Needs |
|---|---|---|---|
| **A** | [Chrome extension](extension/) | a button inside Overleaf | Chrome, 2 minutes |
| **B** | [`mechcheck.sty`](latex/mechcheck.sty) | every Overleaf compile | nothing — works on the free plan |
| **C** | [`browser/mechcheck.html`](browser/mechcheck.html) | when you drop a project on it | a browser, nothing else |
| **D** | [mirror + CI](.github/workflows/overleaf-mirror.yml) | every 30 min, automatically | Overleaf premium (git bridge) |
| **E** | [`mechcheck` CLI](mechcheck/) | locally and in CI | Python 3.10+ |

**If you want no Python and no GitHub: use A and B.** The extension puts the
checks in the Overleaf window itself — it reads the project straight from
Overleaf, and reference verification works there because a Manifest V3 service
worker is allowed to make cross-origin requests. Layer B then covers every
compile automatically, on any plan.

Setup: **[docs/chrome-extension.md](docs/chrome-extension.md)** (extension) ·
**[docs/browser.md](docs/browser.md)** (standalone page) ·
**[docs/overleaf-setup.md](docs/overleaf-setup.md)** (Overleaf and CI).

---

## What it actually catches

A real example, run against a deliberately flawed paper:

```
main.tex
  x error VEN002:1   missing \documentclass option `manuscript` (required for submission)
  x error VEN002:1   \documentclass option `sigconf` must not be used for submission
  x error ANON001:4  \author is present but the document is not compiled with `anonymous`
  x error ANON003:12 identifying link: https://github.com/mcolley
  ! warn  ANON004:13 funding mentioned: 'funded by'
  x error ACC001:14  figure has no \Description (alt text)
  ! warn  ACC004:19  'The red line' identifies data by colour alone
  x error VEN003:20  \bibliographystyle{plain} but ACM AutomotiveUI requires ACM-Reference-Format
  i info  POL006:11  'F = 4.7' has no degrees of freedom
  i info  POL007:11  'p < .05' is reported with no effect size nearby
```

And against a bibliography drafted with LLM help:

```
refs.bib
  x error BIO001:13  `baddoi`: DOI 10.1145/9999999.9999999 does not resolve
  x error BIO002:17  `mismatch`: the DOI resolves to "A Design Space for External
                     Communication of Autonomous Vehicles" (similarity 0.11)
  ! warn  BIO005:23  `hallucinated` could not be found in Crossref, DBLP or OpenAlex.
                     Closest match: "The calibration of trust in an automated system" (0.43)
  x error BIB006:30  `etal` has 'et al.' in the author field
```

The full list is in **[docs/rules.md](docs/rules.md)** — generated from the code,
so it cannot drift.

---

## Design commitments

These are the properties that decide whether a mandatory checker is a help or a
tax, so they are worth stating explicitly.

**Only mechanical things.** Every rule is decidable from the characters on the
page. Nothing here has an opinion about whether the contribution is
interesting, whether the related work is adequate, or whether the writing is
good. That boundary is what makes it safe to require: passing means "nothing
embarrassing is left", not "this is good work".

**A false positive is worse than a miss.** A checker that cries wolf gets
ignored, and then the real findings go with it. Where a rule cannot be sure, it
reports INFO, or nothing. `BIO005` (reference not found anywhere) is a warning,
never an error, because German-language theses, standards and older workshop
papers are genuinely missing from the indexes.

**Never accuse.** The reference checks state facts — "this DOI does not
resolve", "the DOI resolves to a different title" — and leave the conclusion to
a person. There is a real difference between a mistyped DOI and a fabricated
citation, and a tool cannot tell them apart.

**Nothing blocks a draft.** `--stage draft` reports everything and fails
nothing. Strictness arrives at `submission`, and at `final` every warning
becomes an error. Students meet the checker as a helper long before it becomes a
gate.

**Always an escape hatch, always visible.** Any rule can be silenced on one
line, with a reason that stays in the diff:

```latex
\includegraphics{divider}  % mechcheck: off ACC001 -- decorative rule, no content
```

**Adoptable mid-thesis.** `mechcheck baseline .` freezes today's findings so only
*new* problems fail. Nobody has to fix 300 warnings before they can benefit.

---

## For supervisors

```bash
python scripts/digest.py --config students.yaml --out digest.md --offline
```

One table per week: who is compiling, who is stuck, word count, error count,
days since the last commit, days to the deadline, and what each thesis is
failing on most. `.github/workflows/supervisor-digest.yml` posts it as an issue
every Monday.

The digest deliberately reports mechanical counts only. It is a triage list for
deciding who needs a message this week — not an assessment.

### Start students somewhere clean

Every check here is remedial: it catches a mistake after it is made. The
preventive half is a document where the mistake is harder to make.

**[M-Colley/thesis-template](https://github.com/M-Colley/thesis-template)** is a
LaTeX thesis wired up for all of this — `mechcheck.sty` already loaded, the
house style already applied, each section a prompt that turns into a
compilation error if it survives to the final version. A fresh copy reports
zero findings from this checker, online checks included, so the first finding a
student sees is genuinely theirs.

---

## Venue packs

Submission requirements are **data**, not code
([`mechcheck/venues/*.yaml`](mechcheck/venues/)), because they change every
cycle. Adding a venue means adding a file.

```yaml
document_class: acmart
bibliography_style: ACM-Reference-Format
class_options:
  submission:
    required: [manuscript]
    forbidden: [sigconf]
length:
  unit: pages
  min_pages: 6
  max_pages: 13
  excludes: 'references do not count towards the submission page limit'
```

Every pack carries a `verified` date and a `source_url`, and `VEN008` reminds you
when a pack is more than nine months old. **The packs are a convenience, not an
authority: the call for papers is the authority.** Each pack also lists what
could not be verified — see the `uncertain:` block at the bottom of each file.

Shipped: `chi`, `assets`, `autoui`, `imwut`, `trf`.

---

## Everyday use

```bash
mechcheck check .                          # the default: thesis, submission stage
mechcheck check . --stage draft            # report everything, fail nothing
mechcheck check . --venue assets           # + ASSETS accessibility requirements
mechcheck check . --offline                # skip the network lookups
mechcheck check . --build-dir build        # also read the compiled PDF and log
mechcheck explain FIG003                   # what one rule means, and why
mechcheck rules --category accessibility   # what exists
mechcheck baseline .                       # adopt mid-project
mechcheck init . --with-ci --with-sty      # set up a project
```

Output formats: `text`, `markdown` (job summaries and PR comments), `github`
(inline annotations), `sarif` (GitHub code scanning), `json` (the digest).

---

## Repository layout

```
mechcheck/            the checker
  rules/              one module per rule family, prefix per module
  venues/             venue packs (data)
  texsource.py        the LaTeX parser everything else reads through
  bibtex.py           a tolerant .bib reader
  net.py              Crossref / OpenAlex / DBLP, cached and polite
extension/          the Chrome extension (engine.js is generated)
browser/
  mechcheck.html      the entire checker in one file, no install
  test-engine.mjs     runs that engine in Node against the Python fixtures
  build-extension.mjs regenerates the extension's copy of the engine
latex/
  mechcheck.sty       the in-Overleaf layer
  demo/               a deliberately flawed document CI compiles to prove it works
.github/workflows/
  mechcheck.yml       tests + compiles the .sty against a real LaTeX install
  overleaf-mirror.yml pulls from Overleaf on a schedule
  supervisor-digest.yml  the Monday table
scripts/digest.py     the multi-repository digest
docs/                 setup, rule reference, workflow design
tests/                194 tests
```

## Status

Python side: 207 tests passing, and the bibliography verification has been run
against the live Crossref, OpenAlex and DBLP APIs.

Browser side: 54 checks passing (`node browser/test-engine.mjs`), and the page
itself was driven in a real browser — zip reading, filtering, export, and both
colour themes.

Extension: 17 checks passing in a real browser via `extension/test-harness.html`
— panel rendering, project-zip reading, filtering, export, error path. Not yet
loaded in Chrome against a live Overleaf session; see the end of
[docs/chrome-extension.md](docs/chrome-extension.md).

`latex/mechcheck.sty` has **not** been compile-tested yet — there is no TeX
installation on the machine it was written on. The `latex` job in
`.github/workflows/mechcheck.yml` exists precisely to close that gap: it installs
TeX Live, compiles `latex/demo/demo.tex`, and asserts both that the planted
faults are detected and that the well-formed figure is not. Run it before giving
the `.sty` to students.

---

## Licence

MIT — see [LICENSE](LICENSE). Use it, change it, hand it to your students.

If it saves you an evening, or if a rule fires wrongly on your paper, an issue
is welcome. False positives are the most useful thing you can report: this
checker earns its authority by not crying wolf, and every wrong finding is a
bug worth fixing.
