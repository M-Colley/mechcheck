# mechcheck

[![self-test](https://github.com/M-Colley/mechcheck/actions/workflows/mechcheck.yml/badge.svg)](https://github.com/M-Colley/mechcheck/actions/workflows/mechcheck.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

Mechanical checks for LaTeX theses and papers: the boring layer of review,
automated, so supervision time goes to the argument instead of the formatting.

157 rules across figures, cross-references, abbreviations, prose mechanics,
bibliography hygiene, **bibliography verification against Crossref/OpenAlex/DBLP**,
compile-log analysis, accessibility, anonymity, reporting conventions,
**p-values recomputed from the test statistic**, **one name per concept**,
the things that compile on your laptop but not on
Overleaf, **the desk-reject screen a venue runs before review**, and per-venue
submission requirements for twelve venues: CHI, ASSETS, AutomotiveUI, IMWUT,
MobileHCI, UIST, CHI PLAY, Transportation Research Part F, and the machine
learning venues NeurIPS, ICLR, CVPR and AAAI.

**Nothing to install.** Save
[`browser/mechcheck.html`](browser/mechcheck.html), double-click it, and drop
your Overleaf `.zip` on the page. Or load [`extension/`](extension/) in Chrome
and get a button inside Overleaf itself.

If you would rather have a command line:

```bash
pip install "git+https://github.com/M-Colley/mechcheck"
mechcheck check .                       # a CHI paper at submission — the default
mechcheck check . --profile thesis      # a thesis: no venue, thesis formalities on
mechcheck check . --venue uist --profile paper-anonymous --stage final
mechcheck fix .                         # apply the unambiguous corrections
```

**What it assumes.** With nothing configured, a document is taken to be a
paper being submitted to CHI. A thesis says so once — `--profile thesis`, or
`profile: thesis` in `mechcheck.yaml`, which `mechcheck init` writes — and
that profile turns the venue off with it.

---

## Installation

Pick the row that matches how you work. Each is spelt out below the table.

| You want | You need | Do this |
|---|---|---|
| a page to drop a zip on | any browser | save `browser/mechcheck.html`, double-click it |
| a button inside Overleaf | Chrome, Edge or Brave | load `extension/` unpacked — two minutes, no store account |
| checks on every Overleaf compile | nothing; works on the free plan | upload `latex/mechcheck.sty`, add `\usepackage{mechcheck}` |
| a command line, and CI | Python 3.12 or newer | `pip install "git+https://github.com/M-Colley/mechcheck"` |

### The page and the extension

Neither needs Python, and nothing leaves your machine except the reference
lookups you switch on. Setup: [docs/browser.md](docs/browser.md) and
[docs/chrome-extension.md](docs/chrome-extension.md).

### The command line

mechcheck is not on PyPI yet, so pip installs it from this repository. You
need Python 3.12 or newer and git. There are no other dependencies: the
standard library does the parsing, the configuration and the network.

```bash
pip install "git+https://github.com/M-Colley/mechcheck"
```

To work on it instead, install a clone in editable mode:

```bash
git clone https://github.com/M-Colley/mechcheck
cd mechcheck
pip install -e ".[dev]"      # adds pytest and PyYAML
```

Confirm it landed:

```bash
mechcheck rules | tail -1
```

prints `157 rules`. Then run it on the self-test document, whose answer is
known in advance:

```bash
mechcheck check tests/fixtures/selftest --profile paper-anonymous --venue autoui --offline
```

Expect `12 error(s), 15 warning(s), 10 note(s)`. If you see that line, the
whole chain works.

**If `mechcheck` is not recognised** — the normal state of a fresh Python on
Windows, where pip's `Scripts` directory is not on PATH — every command also
works as

```bash
python -m mechcheck check .
```

**Optional: PyYAML.** `mechcheck.yaml` is read by a built-in parser that
understands the small YAML subset the documentation uses. With PyYAML
installed (`pip install PyYAML`) the full language is accepted. Nothing that
ships here needs it.

**Network.** The seven `BIO*` rules ask Crossref, OpenAlex and DBLP whether
the works you cite exist. They need internet access, cache every answer for
30 days under `~/.cache/mechcheck`, and are skipped with `--offline`. Put your
e-mail address under `mailto:` in `mechcheck.yaml` (or in the `MECHCHECK_MAILTO`
environment variable) to join Crossref's polite pool: it is faster, and it is
the courteous thing to do.

**Upgrading and removing.** Re-run the `pip install` line with `--upgrade`;
an editable install follows `git pull`. `pip uninstall mechcheck` removes it.

### Inside Overleaf

`latex/mechcheck.sty` runs the checks LaTeX itself can make — floats,
captions, alt text, and with `[crossref]` labels and references — inside every
compile, on any Overleaf plan. Upload it to the project and add
`\usepackage{mechcheck}` to the preamble. Findings appear as package warnings
in the log panel and in `mechcheck-report.txt` under *Other logs & files*.
[docs/overleaf-setup.md](docs/overleaf-setup.md) has the details, and the
GitHub mirror that brings the full rule set to an Overleaf project.

### In a project's CI

```bash
mechcheck init . --with-ci --with-sty
```

writes a `mechcheck.yaml`, a GitHub Actions workflow that installs mechcheck
from this repository and posts findings as annotations and a job summary, and
a copy of the `.sty`.

### For working on mechcheck itself

| To run | You need | Command |
|---|---|---|
| the Python suite | `pip install -e ".[dev]"` | `python -m pytest -q` |
| the browser engine | Node 18 or newer | `node browser/test-engine.mjs` |
| the extension harness | any browser | `node browser/build-extension.mjs`, then open `extension/test-harness.built.html` |
| the LaTeX package | TeX Live, or any TeX with `latexmk` | `bash latex/verify-sty.sh` |

The LaTeX script looks for TeX Live in its usual install locations when
`latexmk` is not on PATH, which on Windows it usually is not. After editing
`browser/mechcheck.html`, run the build script: `extension/engine.js` is
generated from the page, and CI fails if the two drift apart. After adding or
changing a rule, regenerate the reference: `mechcheck rules --markdown > docs/rules.md`.
After editing a venue pack, run `python scripts/sync-venues.py`: the page
carries its own copy of the packs, and the browser suite compares the two
pack by pack.

### When something does not work

| Symptom | Cause, and what to do |
|---|---|
| `mechcheck` is not recognised or not found | pip's script directory is not on PATH. Use `python -m mechcheck ...`, or add the directory pip named during installation. |
| `No module named mechcheck` | A different Python than the one you installed into. Run `python -m pip install ...` with the same `python` you use to run it. |
| `N rule(s) did not run` at the end of a report | Each skipped rule has a reason: `--offline`, no compiled `.log`/`.pdf` to read, or disabled by the profile. `mechcheck check . --show-skipped` lists them. |
| `latexmk not found` from `verify-sty.sh` | Install TeX Live, or add its `bin` directory to PATH. The script tries the standard locations first. |
| `docs/rules.md is stale` in CI | A rule changed. Run `mechcheck rules --markdown > docs/rules.md` and commit the result. |
| The `.sty` reports every figure as missing its caption | It could not attach to your document class; the report file says so. Use the command line for those checks. |

---

## Five ways to run it

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

Against a bibliography drafted with LLM help:

```
refs.bib
  x error BIO001:13  `baddoi`: DOI 10.1145/9999999.9999999 does not resolve
  x error BIO002:17  `mismatch`: the DOI resolves to "A Design Space for External
                     Communication of Autonomous Vehicles" (similarity 0.11)
  ! warn  BIO005:23  `hallucinated` could not be found in Crossref, DBLP or OpenAlex.
                     Closest match: "The calibration of trust in an automated system" (0.43)
  x error BIB006:30  `etal` has 'et al.' in the author field
```

And against a project that compiles on the author's laptop and nowhere else:

```
main.tex
  ! warn  STR010:3   package `subfigure` is obsolete
  x error STR013:6   `Chapters/Intro` is stored as `chapters/intro.tex`; Overleaf is case-sensitive and will not find it
  ! warn  STY020:7   'et. al.' should be 'et al.'
  ! warn  REF010:8   consecutive \cite commands print as separate brackets
  ! warn  STY016:8   bare URL: https://osf.io/abcde
  x error FIG012:10  `Figures/Plot.PNG` is stored as `figures/plot.png`; Overleaf is case-sensitive and will not find it
```

Windows and macOS open `Figures/Plot.PNG` when the file is `figures/plot.png`;
Linux, and therefore Overleaf and every CI runner, do not. `mechcheck fix`
rewrites the path, merges the citations, wraps the URL and corrects the
"et al." — the corrections with exactly one right answer.

And against the screen a venue runs before anyone reviews the paper:

```
main.tex
  x error POL011:44  white text contains an instruction to the reader: "positive review"
  x error ANON008:8  `smith2024` is a masked reference: the author field is "Anonymous"
  x error ANON006     the PDF XMP metadata author is "Mark Colley"
  ! warn  STY021:19  'Section ??' reads as an unresolved reference
  ! warn  MET001      13,900 words of main text, limit 12000 (references and floats excluded)
  i info  VEN010      2 of 61 references cite SIGCHI/HCI venues (this pack expects at least 4)
```

Those mirror the cards a CHI screening report raises: a masked reference and
an author name in either of the PDF's two metadata blocks are desk-reject
grounds, hidden text addressed to an automated reviewer is a
research-integrity matter, and the length and scope items are advisory
counts, never verdicts. `mechcheck check . --venue chi` runs the lot before
you submit rather than after.

And against the numbers in the results section, which no amount of reading
will catch:

```
main.tex
  ! warn  STA001:6  t(48) = 2.13 gives p = 0.0383, but the paper reports p = .003
  ! warn  STA001:7  F(2, 46) = 4.71 gives p = 0.0138, but the paper reports p = .21,
                    which changes whether the result is significant at 0.05
  ! warn  STA001:8  r(38) = 0.42 gives p = 0.007, but the paper reports p = .48,
                    which changes whether the result is significant at 0.05
  ! warn  STA002:9  p = .000: no p-value is exactly zero; this is a rounded printout
```

`STA001` recomputes the p-value from the test statistic and its degrees of
freedom — `t`, `F`, `r`, `χ²` and `z` — and reports it only when the two
cannot be reconciled. A transposed digit is invisible to a reader and to a
reviewer; arithmetic finds it. Because a wrongly accused author is worse than
a missed error, it compares *intervals* rather than numbers: `t(48) = 2.13`
was rounded from somewhere in [2.125, 2.135], which gives a p-value between
0.0379 and 0.0388, and a finding needs that range to miss the reported
p-value's own rounding interval entirely. One-tailed tests never produce a
finding, because nothing in the text distinguishes one from a mistake. The
same document's correctly reported `t(120) = 2.51, p = .013` stays silent.

The full list is in **[docs/rules.md](docs/rules.md)** — generated from the code,
so it cannot drift.

---

## One name per concept

A reader who meets "self-driving car" on page 12 and "automated vehicle" on
page 13 has to decide whether they are the same thing. Usually they are, and
the decision costs attention that belonged to the argument.

**What the document does is a fact,** so four rules report it and name the
majority without prescribing anything: two names for one concept (`TRM001`),
one term spelled two ways (`TRM003`, "eye-tracking" against "eye tracking"),
one term capitalised inconsistently (`TRM004`), and an abbreviation whose
expansion keeps being written out anyway (`TRM005`). All four are notes, and
all four keep quiet wherever English itself explains the difference — "a
real-time system" beside "runs in real time" is correct twice over.

**Which name to use is a judgement,** so that one lives in the project, not in
this tool. Write it down once:

```yaml
# mechcheck.yaml
terminology:
  - prefer: automated vehicle
    over: [self-driving car, autonomous vehicle, driverless car]
  - variants: [participant, test person, test subject]
```

`prefer`/`over` is a house rule: `TRM002` reports every use of the other
names, and `mechcheck fix .` rewrites them — carrying the capital, the plural
and the article, so "A self-driving car" becomes "An automated vehicle".
`variants` only asks for consistency and prescribes nothing.

You do not have to invent the list. Run it on a finished thesis:

```bash
mechcheck terms .
```

It prints what that document calls things, and ends with the `terminology:`
block ready to paste into your group's configuration.

**Where this applies.** `mechcheck.yaml` is now read by every layer — the
command line, the standalone page and the Chrome extension all honour the same
file, so a student who drops a project on the page gets the same answer CI
does. Before, the page ignored it, and a rule a supervisor had switched off
kept firing for the student.

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
papers are genuinely missing from the indexes. Every rule is tested in both
directions, and every false positive reported from real use becomes a
regression test.

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
compilation error if it survives to the final version. The template is kept
at zero findings from this checker, online checks included, so the first
finding a student sees is genuinely theirs.

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

Shipped: `chi`, `assets`, `autoui`, `imwut`, `trf`, `mobilehci`, `uist`,
`chiplay`, `neurips`, `iclr`, `cvpr`, `aaai` — twelve packs, each with the date
it was read and the page it was read from. `mechcheck venues` lists them.

---

## Everyday use

```bash
mechcheck check .                          # the default: a CHI paper at submission
mechcheck check . --profile thesis         # a thesis: no venue, thesis formalities on
mechcheck check . --stage draft            # report everything, fail nothing
mechcheck check . --venue assets           # + ASSETS accessibility requirements
mechcheck check . --offline                # skip the network lookups
mechcheck check . --build-dir build        # also read the compiled PDF and log
mechcheck check . --show-skipped           # which rules did not run, and why
mechcheck terms .                          # what this document calls things
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
extension/            the Chrome extension (engine.js is generated)
browser/
  mechcheck.html      the entire checker in one file, no install
  test-engine.mjs     runs that engine in Node against the Python fixtures
  build-extension.mjs regenerates the extension's copy of the engine
latex/
  mechcheck.sty       the in-Overleaf layer
  verify-sty.sh       compiles the demo against a real TeX and checks the report
  demo/               a deliberately flawed document CI compiles to prove it works
.github/workflows/
  mechcheck.yml       tests + compiles the .sty against a real LaTeX install
  overleaf-mirror.yml pulls from Overleaf on a schedule
  supervisor-digest.yml  the Monday table
scripts/digest.py     the multi-repository digest
docs/                 setup, rule reference, workflow design, the self-test procedure
tests/                the Python suite, and the fixtures both engines are checked against
```

## Status

Python side: 857 tests passing, and the bibliography verification has been run
against the live Crossref, OpenAlex and DBLP APIs.

Browser side: 327 checks passing (`node browser/test-engine.mjs`) against the
same fixtures as the Python suite — including the assertion that both engines
produce exactly the same findings on the self-test document, and that both
readers of `mechcheck.yaml` agree on this repository's own configuration.

Extension: 35 checks passing in a real browser via `extension/test-harness.html`
— panel rendering, project-zip reading, filtering, export, error path, and the
gutter markers against a copy of Overleaf's editor structure — and loaded
against a live Overleaf project once, on 2026-08-28. The markers are the one
part that reads Overleaf's editor DOM rather than its download URL, so they
are verified against that copy and not against live Overleaf; if Overleaf
changes its editor they stop appearing and nothing else is affected. Re-run
[docs/testing.md](docs/testing.md) test 1 after updating.

`latex/mechcheck.sty`: 14 checks passing against TeX Live 2026
(`bash latex/verify-sty.sh`), the same script CI runs: it compiles the flawed
demo and asserts both that the planted faults are reported and that the
well-formed figure is not. It has not yet been verified inside Overleaf
itself; that is test 3 in [docs/testing.md](docs/testing.md).

---

## Licence

MIT — see [LICENSE](LICENSE). Use it, change it, hand it to your students.

If it saves you an evening, or if a rule fires wrongly on your paper, an issue
is welcome. False positives are the most useful thing you can report: this
checker earns its authority by not crying wolf, and every wrong finding is a
bug worth fixing.
