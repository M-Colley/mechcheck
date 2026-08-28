# Testing it yourself

Three tests, about fifteen minutes. Each one has an unambiguous pass condition,
so you never have to judge whether it "looks right".

The fixture for all three is [`latex/overleaf-selftest.tex`](../latex/overleaf-selftest.tex):
a deliberately awful paper with 37 planted faults. It is not an example of good
writing — it exists so the answer is known in advance.

---

## Setup (once)

Make a new Overleaf project and put two files in it:

1. **`main.tex`** — the contents of `latex/overleaf-selftest.tex`
2. **`refs.bib`** — this:

```bibtex
@inproceedings{colley2021,
  author = {Colley, Mark and Rukzio, Enrico},
  title = {A Design Space for External Communication of Autonomous Vehicles},
  booktitle = {12th International Conference on Automotive User Interfaces},
  year = {2020},
  doi = {10.1145/3409120.3410646}
}
@article{rukzio2020,
  author = {Rukzio, Enrico et al.},
  title = {Another Work},
  journal = {Journal of Things},
  year = {2021},
  pages = {45-58}
}
```

It will not compile as-is — `acmart` will complain about the missing CCS block.
That does not matter for tests 1 and 2, which read the source, not the PDF.

---

## Test 1 — the Chrome extension (the one that is unverified)

1. `chrome://extensions` → **Developer mode** on → **Load unpacked** → pick the
   `extension/` folder.
2. Open the Overleaf project. A **mechcheck** button should appear bottom right.
3. Click it. Set **Profile** = *Paper (anonymous review)*, **Venue** =
   *ACM AutomotiveUI*, **Stage** = *Submission*.
4. Press **Check**.

**Pass:** the panel shows **12 errors, 15 warnings, 10 notes** — 37 findings.

Spot-check that these specific ones appear, because each proves a different
part of the chain is alive:

| Rule | What it proves |
|---|---|
| `VEN002` ×2 | the venue pack loaded and knows AutoUI wants `manuscript`, not `sigconf` |
| `ANON001` | the anonymity sweep is on and found the author block |
| `REF008` ×3 | your `\autoref` preference — `Figure~\ref`, `Table~\ref`, `Section~\ref` |
| `REF009` ×2 | your `\citet` preference — "Colley et al." and "Rukzio and Colley" |
| `ABB001` | it read the whole document, not just the visible part (ADS defined twice, far apart) |
| `BIB006` | it read `refs.bib` out of the project zip |

**Then test verification:** tick **verify refs** and press Check again. It takes
a few seconds. `BIO001` should *not* appear — the DOI in `refs.bib` is real. To
prove the check is actually running, change that DOI to `10.1145/9999999.9999999`
and re-check: `BIO001` should appear, saying the DOI does not resolve.

**If it fails,** tell me which of these it was:

| Symptom | What it means |
|---|---|
| No button appears | the content script did not inject — check `chrome://extensions` for an error under mechcheck, and confirm the URL is `overleaf.com/project/…` |
| "Overleaf refused the download (HTTP 4xx)" | the download endpoint moved or the session is not shared — this is the thing I could not verify from here |
| Findings appear but `verify refs` finds nothing | the service worker relay is not working; check the extension's *service worker* console |
| Counts differ from 12/15/10 | send me the numbers — that is a real disagreement between us |

---

## Test 2 — the standalone page (no install)

1. Overleaf: **Menu → Download → Source** to get the `.zip`.
2. Open `browser/mechcheck.html` by double-clicking it.
3. Set the same three controls, drop the `.zip` on the page.

**Pass:** the same **12 / 15 / 10**. If test 1 and test 2 disagree, that is a
bug and I want to know.

Reference verification works here too *because you opened the file locally*. From
a shared link it is blocked, and the page says so rather than reporting nothing.

---

## Test 3 — the compile-time package (inside Overleaf)

This is the layer that runs on every recompile, on any Overleaf plan.

1. Upload [`latex/mechcheck.sty`](../latex/mechcheck.sty) into the project.
2. In `main.tex`, uncomment:

   ```latex
   \usepackage[report]{mechcheck}
   ```

3. To make it compile, either switch `\documentclass[sigconf,review]{acmart}` to
   `\documentclass{article}`, or add a CCS block. `article` is quicker.
4. Recompile.

**Pass, three ways:**

- The **last page of the PDF** is a mechcheck report (that is what `[report]` does).
- **Logs and output files** shows `Package mechcheck Warning:` lines.
- `mechcheck-report.txt` appears under *Other logs & files* and reads like:

  ```
  warn  MC003 main:64 --- figure has no label
  error MC001 main:64 --- figure has no Description (alt text is required by ACM)
  ```

Expect `MC001` on the figures (no `\Description`) and, with
`\usepackage[crossref,report]{mechcheck}`, also `MC006` for `\ref{sec:nowhere}`.

**The important negative:** the figure that has a caption *and* a label should
**not** be reported for those. A checker that flags correct input is worse than
none, so if you see a complaint about a well-formed float, that is a bug.

Remove `[report]` before you use the package on real work — it adds a page.

---

## What I have already run

So you know where the gaps are rather than re-testing what is covered:

| | Verified how |
|---|---|
| 119 rules, Python | 253 tests |
| 119 rules, browser engine | 63 checks in Node, same fixtures |
| Both agree on this exact document | asserted in both suites, 37 findings |
| Extension panel, zip reading, filters | 17 checks in a real browser |
| `mechcheck.sty` | 12 checks against TeX Live 2026 |
| **Extension in Chrome on live Overleaf** | **not verified — that is test 1** |
| **`mechcheck.sty` inside Overleaf** | **not verified — that is test 3** |

Tests 2 is a sanity check; tests 1 and 3 are the ones that cover genuinely
unverified ground.

---

## Re-running my suites

Nothing here is needed to *use* the tool, only to change it.

```bash
node browser/test-engine.mjs      # the browser engine, no dependencies
python -m pytest -q               # the Python checker
bash latex/verify-sty.sh          # the LaTeX package, needs TeX on PATH
```

The extension harness is a file you open:
`extension/test-harness.built.html`.

On this machine TeX is at `C:\texlive\2026\bin\windows`, which is not on PATH —
prefix with:

```bash
export PATH="/c/texlive/2026/bin/windows:$PATH"
```
