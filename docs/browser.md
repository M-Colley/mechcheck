# The browser version — no Python, no GitHub, no server

`browser/mechcheck.html` is the whole checker in one file: all 149 rules, the
five venue packs, and the reference verification. It runs in the browser, on
the machine in front of you. Nothing is uploaded, and there is nothing to
install.

## Use it

1. Save `browser/mechcheck.html` anywhere — Desktop is fine.
2. Double-click it.
3. In Overleaf: **Menu → Download → Source** to get the project `.zip`.
4. Drop that `.zip` onto the page.

That is the entire workflow. Add the `.log` and `.pdf` from Overleaf's *Other
logs & files* panel and the compile-log, page-count and PDF-metadata checks
switch on too.

You can also drop a folder, or a handful of loose `.tex` and `.bib` files.

## Why open it locally rather than from a link

Reference verification asks Crossref, OpenAlex and DBLP whether the works you
cite exist. A page opened from a local file may make those requests; a page
served from a sandboxed host usually may not.

| | Static checks | Reference verification |
|---|---|---|
| Opened as a local file (double-click) | yes | **yes** |
| Opened from a shared/published link | yes | usually blocked |

The page detects the difference and says so rather than silently reporting
nothing. Everything except the seven `BIO*` rules works either way.

Verification results are cached in the browser, so re-checking an unchanged
bibliography is instant and costs the APIs nothing.

## What you can change on the page

| Control | What it does |
|---|---|
| **Profile** | thesis · paper · paper (anonymous review) · camera-ready · everything |
| **Stage** | `draft` reports but never blocks · `submission` · `final` promotes warnings to errors |
| **Venue** | CHI · ASSETS · AutomotiveUI · IMWUT · TRF — adds that venue's requirements |
| **Verify online** | turns the seven reference-verification rules on |

The settings are remembered in the browser, so each student sets them once.

**The project's own `mechcheck.yaml` is read too.** If the zip you drop in
contains one, the page applies it: rules it disables stay quiet, severities it
changes apply, per-rule options and the project's own vocabulary
(`terminology:`) are used, and its `profile`, `stage` and `venue` are adopted
into the three controls above — which the page says in a line under them, and
which you can still change afterwards. This is the same file the command line
and CI read, so a student checking here and a supervisor checking in CI now
see the same findings.

Findings can be filtered by severity, by category, or by a text search, and
exported with **Copy as Markdown** / **Download report** — which is what to
paste into an email or a supervision issue.

## Fixing the trivial ones

Some findings have exactly one right answer. For those, press **Fix N
automatically** and the page hands you the corrected file: copy it, open that
file in Overleaf, select all, paste.

| Fixed automatically | Left to you |
|---|---|
| `ABB001` a second expansion of an abbreviation | `ACC001` alt text — no machine can write it |
| `REF008` `Figure~\ref{x}` becomes `\autoref{x}` | `BIO*` whether a reference is real |
| `REF009` `Colley et al.~\cite{k}` becomes `\citet{k}` | anything needing a sentence rewritten |
| `STY003` a repeated word | |
| `STY005` a space before punctuation | |
| `STY007` `10-20` becomes `10--20` | |
| `STY016` a bare URL becomes `\url{...}` | |
| `STY020` `et. al.` becomes `et al.` | |
| `TRM002` the project's own term, from `terminology:` | `TRM001` which of two names to prefer — that is your choice to make |

A page cannot write into an Overleaf project, which is why it gives you the
file rather than editing it. Two things make that safe to paste:

* **Only unambiguous rules carry a fix.** A rule earns one when the correction
  is fully determined, never when it needs judgement.
* **Overlapping edits are refused, not merged.** If two fixes touch the same
  span, one applies and the other is reported as skipped.

The same fixes are available from the command line with `mechcheck fix .`,
which additionally re-checks the project afterwards and reports anything that
was not there before.

## Silencing a check

Same syntax as every other layer, and it stays visible in the source:

```latex
\includegraphics{divider}  % mechcheck: off ACC001 -- decorative rule, nothing to describe
```

`% mechcheck: off-file BIO005 -- German-language sources, not indexed` silences
a rule for a whole file.

## Giving it to students

Three options, in increasing order of how much you have to maintain:

1. **Send the file.** It is one HTML file. Email it, or put it in the shared
   drive. It works offline, forever, with no dependency that can rot.
2. **Put it on any web space** you already have. A single static file, no build
   step. Students bookmark it.
3. **Publish it as a link** from this repository. Convenient to share, but
   reference verification will be blocked there — tell students to save the file
   locally when they want that.

## Keeping it honest

The browser version and the Python version share their logic by construction:
`browser/test-engine.mjs` runs the browser engine, in Node, against the same
fixtures as the Python test-suite and asserts the same rules fire.

```bash
node browser/test-engine.mjs
```

226 checks, no dependencies beyond Node. If the two implementations ever
disagree, that suite is what tells you.

## What it cannot do

- **Compile your document.** It reads LaTeX, it does not typeset it. Page counts
  need the `.pdf`; overfull boxes and undefined references need the `.log`.
- **Run automatically.** Nothing in a browser can watch your Overleaf project.
  For automatic checks on every compile, use `latex/mechcheck.sty`, which runs
  inside Overleaf itself (see [overleaf-setup.md](overleaf-setup.md)).

Those two gaps are exactly what the other two layers cover, which is why all
three exist.
