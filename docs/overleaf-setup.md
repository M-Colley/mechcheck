# Running this against Overleaf

## The constraint that shapes everything

Two facts decide the whole design, and both were checked against Overleaf's own
documentation on 2026-08-27:

1. **Overleaf's Git integration and GitHub synchronisation are premium
   features.** They require a paid individual subscription, a group/institutional
   licence, or Overleaf Commons. Students on the free plan have neither.
2. **GitHub synchronisation is manual.** Overleaf's documentation states plainly
   that "Synchronization between GitHub and Overleaf does not happen
   automatically" — commits reach GitHub only when someone presses *Push Overleaf
   changes to GitHub*. There is no webhook.

So "CI runs on every Overleaf edit" is not achievable as a push. Three layers get
as close as the platform allows, and you can use any combination of them.

| Layer | Runs when | Needs premium? | Catches |
|---|---|---|---|
| A. `mechcheck.sty` | every compile, inside Overleaf | no | floats, captions, alt text, cross-references |
| B. Mirror + CI | every 30 min, automatically | yes (git bridge) | everything, including reference verification |
| C. Manual CI | when someone pushes | yes (GitHub sync) | everything |

**Recommendation:** give every student layer A on day one — it costs them one
`\usepackage` line and works on any plan. Add layer B for the theses you care
most about, and for your own papers.

---

## Layer A — checks inside the Overleaf compile

Zero infrastructure. Works on the free plan. Runs every time the student hits
recompile, which for most students is many times an hour.

1. Upload `latex/mechcheck.sty` into the Overleaf project (drag it into the file
   list, or add it to your template project so every student inherits it).
2. Add to the preamble:

   ```latex
   \usepackage{mechcheck}
   ```

3. That is the whole setup. Findings appear:
   - in the **Logs and output files** panel as package warnings;
   - in `mechcheck-report.txt`, downloadable from *Other logs & files*.

   Add `[report]` to typeset a summary page at the end of the PDF while
   drafting — it makes the findings impossible to ignore, which is the point:

   ```latex
   \usepackage[report]{mechcheck}
   ```

### What layer A checks

| Rule | Meaning |
|---|---|
| `MC001` | figure has no `\Description` (ACM requires alt text) |
| `MC002` | float has no `\caption` |
| `MC003` | float has no `\label` |
| `MC004` | `\label` placed before `\caption` — the reference will show the wrong number |
| `MC005` | label never referenced *(needs `[crossref]`)* |
| `MC006` | reference to an undefined label *(needs `[crossref]`)* |
| `MC007` | duplicate label *(needs `[crossref]`)* |

By default the package only uses LaTeX's own hooks and redefines nothing. The
cross-reference checks need the actual argument of every `\label` and `\ref`,
which means patching those commands, so they are opt-in:

```latex
\usepackage[crossref]{mechcheck}
```

### Safety

The package is written so a bug in it cannot break a student's document:

- it never raises a LaTeX error unless you load it with `[strict]`;
- it redefines nothing at all in its default configuration;
- it **verifies its own instrumentation**: if the `\caption` hook never fires in
  a document that contains floats, it concludes it could not attach to that
  class, discards its float findings, and says so — rather than reporting every
  figure in the thesis as missing a caption.

If anything still goes wrong, `\usepackage[off]{mechcheck}` disables it entirely.

---

## Layer B — mirror from Overleaf, then run the full checks

This is the layer that makes the checks *automatic* despite the manual sync: the
repository pulls from Overleaf rather than waiting to be pushed to.

```
Overleaf project ──(git bridge, polled every 30 min)──► GitHub repo ──► CI ──► findings
```

### Setup

1. **Get the project id.** It is the last part of the Overleaf URL:
   `https://www.overleaf.com/project/`**`64f0c1e2ab34cd0098765432`**

2. **Create a Git authentication token** in Overleaf: *Account Settings → Git
   integration → new token*. Copy it; Overleaf shows it once.

3. **In the GitHub repository**, add two secrets
   (*Settings → Secrets and variables → Actions*):

   | Secret | Value |
   |---|---|
   | `OVERLEAF_PROJECT_ID` | the id from step 1 |
   | `OVERLEAF_GIT_TOKEN` | the token from step 2 |

4. **Copy the two workflows** into the repository:
   - `.github/workflows/overleaf-mirror.yml` — pulls Overleaf into `paper/`
   - `.github/workflows/mechcheck.yml` — runs the checks on what arrives

5. Trigger the mirror once by hand (*Actions → mirror from Overleaf → Run
   workflow*) to confirm the credentials work.

### On polling politely

Overleaf's documentation notes that automated polling of the git bridge can
trigger rate limiting. The shipped schedule is every 30 minutes during weekday
working hours, which is frequent enough that feedback lands while the student is
still writing and infrequent enough to stay a good citizen. Do not tighten it
without a reason.

### If the student has no premium account

Their Overleaf project cannot be cloned. Options, in order of preference:

1. Ask whether your institution has an Overleaf licence — many German
   universities do, and it usually unlocks exactly this.
2. Have the student work in GitHub-backed Overleaf *from your* template: if
   **you** own the project, your premium features apply to it.
3. Fall back to layer A plus a checkpoint check: the student downloads the
   project as a zip at each milestone and you run `mechcheck check` on it. Not
   continuous, but it still front-loads the mechanical review.

---

## Layer C — GitHub sync, for people already using git

If you already work through GitHub sync, you need nothing extra: pushes trigger
`.github/workflows/mechcheck.yml`. The only thing worth adding is the habit of
pressing *Push Overleaf changes to GitHub* before asking for feedback — the CI
result is what your supervisor will look at first.

---

## Verifying the setup

```bash
mechcheck check . --venue autoui
```

Expect a report within a few seconds (a minute or two the first time the
bibliography is verified online; afterwards responses are cached).

To see what CI will do without waiting for CI:

```bash
mechcheck check . --format markdown --output preview.md
```

## What to check when it does not work

| Symptom | Likely cause |
|---|---|
| Mirror fails with authentication error | The Overleaf token expired or the project owner has no premium plan |
| Mirror runs but nothing changes | Nobody has edited the Overleaf project; this is the normal case |
| `mechcheck` reports no files | The main `.tex` was not found — pass `--main path/to/main.tex` |
| Every figure reported as missing a caption | The `.sty` could not attach to your class; the report file will say so. Use the CLI instead |
| Reference checks all skipped | You ran with `--offline`, or the runner had no network |
