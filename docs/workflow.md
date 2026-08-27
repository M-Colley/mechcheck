# Getting the benefit: how to actually use this

The tool is the easy part. What returns hours is the change in workflow around
it — and specifically one change: **the mechanical layer stops being something
you check, and becomes a precondition for your attention.**

---

## The principle

Reading a thesis chapter currently costs you two passes at once: a sloppiness
pass (abbreviations reintroduced, figures never referenced, missing
`\Description`, hallucinated references, compile warnings) and a thinking pass
(is the argument sound, is the study designed right, does the discussion
overreach). The first pass is mechanical, exhausting, and the one that generates
the feedback students find least useful to receive — because you are telling
them something a machine could have told them a month earlier.

Separate the two. Machines take the first pass. You take the second, on
documents that have already passed the first.

The payoff is not only your time. A student who gets "figure 7 is never
referenced" from CI at 11pm on the day they wrote it fixes it in thirty seconds.
The same feedback from you, six weeks later, costs a meeting slot, and arrives
attached to the implicit message that they were careless.

---

## For students

### Rollout, per thesis

**At the kickoff meeting** (15 minutes, once per student):

1. Give them the template project (see below) — it already contains
   `mechcheck.sty`, the config, and the CI workflow.
2. Show them one broken example and one fixed one. Compile it in front of them
   so they see the report appear in Overleaf's output panel.
3. State the rule explicitly and kindly, because an unstated standard is an
   unfair one:

   > "I will read anything you send me. But if the mechanical checks are failing,
   > my comments will start with those, and neither of us wants to spend the
   > meeting on `\Description`. Get it green first — it usually takes ten minutes
   > — and then we can talk about the actual work."

4. Run `mechcheck baseline .` together if they already have a draft, so they
   start from zero findings rather than three hundred.

**During the thesis**, they need nothing from you: the checks run on every
Overleaf compile (layer A) and, if the mirror is set up, every 30 minutes in CI.

**At each milestone**, switch the stage:

| Milestone | Command | Effect |
|---|---|---|
| Weeks 1–8, drafting | `--stage draft` | reports everything, blocks nothing |
| First full draft | `--stage submission` | rule severities apply; errors block |
| Two weeks before submission | `--stage final` | every warning becomes an error |

The escalation matters: a student who meets the checker as a gate on day one
experiences it as bureaucracy. A student who meets it as a helpful nag, and only
later as a gate, experiences it as a safety net.

### What they get out of it

- Feedback in seconds instead of weeks, on exactly the things that are cheap to
  fix immediately and expensive to fix late.
- A defensible answer to "did I forget anything?" the night before submission.
- One fewer way to be embarrassed in a defence: no `??` references, no figure
  nobody discusses, no reference that does not exist.
- Meetings that are about their research.

---

## For you

### The Monday digest

`scripts/digest.py` produces one table for every thesis you supervise:

| | Student | Words | Errors | Warn | Last commit | Due | Most frequent |
|---|---|---:|---:|---:|---|---|---|
| ✅ | A. Student | 14,203 | 0 | 3 | 2026-08-25 | 2026-11-30 (95d) | STY012 ×3 |
| ❌ | B. Student | 8,110 | 17 | 42 | 2026-08-26 | 2026-10-15 (49d) | ACC001 ×9, FIG003 ×5 |
| 🕸️ | C. Student | 2,050 | 4 | 11 | 2026-07-02 (56d ago) | 2026-09-30 (34d) | REF001 ×4 |

The row that matters is C: 34 days to a deadline, 2,000 words, nothing committed
in eight weeks. That is the intervention worth making this week, and you now
know it without having asked anyone how it is going.

Automate it: `.github/workflows/supervisor-digest.yml` opens the digest as an
issue every Monday at 06:00.

### The pre-meeting ritual

Before a supervision meeting, one command:

```bash
mechcheck check ../theses/student-b --stage submission
```

Anything it reports, you do not need to say. Read the discussion section
instead.

### For your own papers

Wire the venue into the project once:

```yaml
# mechcheck.yaml
profile: paper-anonymous
venue: autoui
stage: submission
```

Then the deadline sequence becomes:

| When | Command | What it prevents |
|---|---|---|
| Whenever | `mechcheck check .` | drift |
| Week before | `--stage final` | every warning becomes blocking |
| Submission day | `--profile paper-anonymous` | author block, identifying links, funding statement, PDF metadata |
| On acceptance | `--stage final --profile camera-ready` | `anonymous` left in the class options, wrong template, missing CCS |

The anonymity sweep alone justifies the setup: `ANON006` reads the compiled
PDF's metadata, which is the classic way a carefully anonymised paper gets
de-anonymised anyway.

---

## The template project

The highest-leverage single artefact. Make one Overleaf project, or one GitHub
template repository, containing:

- the thesis or ACM template, pinned to a known-good version
- `mechcheck.sty` in the root, already in the preamble
- `mechcheck.yaml` with your defaults
- `.github/workflows/mechcheck.yml`
- **stubs that are easier to fill in than to delete**: an open science section,
  an AI-use disclosure, an ethics statement, a data availability statement, the
  declaration of originality
- a `SUBMISSION.md` checklist for the things a machine still cannot check

Students cannot send you a thesis that fails the mechanical layer, because the
mechanical layer was in the project before they wrote a word.

```bash
mechcheck init . --with-ci --with-sty --profile thesis
```

---

## What this deliberately does not do

Worth being explicit, because the boundary is the reason to trust the green tick:

- It does not judge whether the contribution is interesting.
- It does not judge whether the related work is adequate — only whether the
  citations resolve.
- It does not judge writing quality. `STY012` counts words in a sentence; it has
  no view on whether the sentence is good.
- It does not detect plagiarism or AI-generated text, and should not be asked to.
- It cannot tell a mistyped DOI from a fabricated citation. It reports the fact
  and leaves the judgement to you.

A green run means "nothing mechanical is left". It never means "this is good".
Say that to students explicitly, or the tool will quietly become the standard.

---

## Where the next hours are

Ranked by hours returned per hour invested, after this:

1. **The template repository.** Half a day, and it applies to every student
   from then on. Nothing else here has that multiplier.
2. **Reviewer-response automation for your own papers.** A structured
   response-to-reviewers document generated from a table of reviewer points,
   with cross-links to the diffs that address them. The bookkeeping in a major
   revision is mechanical, and currently costs a weekend.
3. **The figure pipeline.** Most figure problems (resolution, font size,
   colour-only encoding, missing alt text) come from figures made in one tool
   and dropped into LaTeX. A script that regenerates every figure from its
   source data at submission size, with a checked palette, removes the class of
   problem rather than reporting it.
4. **Study-materials scaffolding.** Preregistration, consent form, demographics
   questionnaire and analysis script share 80% of their content across your
   studies. A generator saves each student two weeks and makes the ethics
   application near-automatic.
5. **A shared, verified group `.bib`.** One file, checked by `BIO001`–`BIO007` in
   CI, that every student and paper draws from. It ends the whole class of
   citation errors at the source instead of catching them per document.
