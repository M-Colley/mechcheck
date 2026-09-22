# The Chrome extension

The nicest version to actually use: a button inside Overleaf. No zip to
download, no page to keep open, and — unlike a sandboxed web page — reference
verification works properly.

## Install (2 minutes, no Web Store account)

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. **Load unpacked** → select the `extension/` folder
4. Open any Overleaf project. A **mechcheck** button appears at the bottom right.

That is it. Chrome keeps it installed across restarts. It works in Edge, Brave
and any other Chromium browser the same way.

## What it does differently from the HTML page

| | Standalone page | Extension |
|---|---|---|
| Getting the project | you download the zip and drop it | it asks Overleaf directly |
| Reference verification | only when opened as a local file | **always works** |
| Compiled `.log` / `.pdf` | you add them yourself | fetched automatically when Overleaf exposes them |
| Where results appear | separate tab | a panel inside the project |

### Why verification works here and not in a published page

Manifest V3 forbids a content script from making cross-origin requests, but a
**service worker with `host_permissions` may**. So every Crossref, OpenAlex and
DBLP lookup is relayed through `background.js`, which is allowed to make it.
That is the whole reason the extension exists as more than a convenience.

### How it reads your project

It fetches `/project/<id>/download/zip` — exactly the file Overleaf's
**Menu → Download → Source** produces — using the session you are already
signed into. Nothing is scraped out of the editor, which would only ever see
the file you have open and would break every time Overleaf ships a new editor.

Compiled output is a best-effort extra: it tries the known `output.log` and
`output.pdf` paths, and if this Overleaf version does not expose them, the
compile and page-count rules simply report as skipped rather than guessing.

## Fixing

After a check, the panel's **Fix N** button appears. It produces the corrected
file for you to copy and paste over the original in Overleaf.

It deliberately does not edit the document for you. Overleaf's editor is a CRDT
synced over a websocket; writing into it behind the editor's back is a good way
to corrupt somebody's paper. Handing over the file is the honest option.

Only rules with exactly one right answer are fixed — abbreviations reintroduced,
`Figure~\ref` to `\autoref`, a name before `\cite` to `\citet`, repeated words,
a space before punctuation, hyphen ranges. Alt text and anything needing
judgement are never touched.

## Privacy

- Runs only on `overleaf.com/project/*` pages.
- The project never leaves your browser.
- The **only** outbound traffic is the bibliographic lookups, only when you tick
  *verify refs*, and only titles and DOIs are sent — to Crossref, OpenAlex and
  DBLP, whose responses are cached locally so repeat checks send nothing.
- No analytics, no account, no server.

## Settings

Set them in the toolbar popup or in the panel itself; they sync across your
Chrome profiles.

| Setting | Notes |
|---|---|
| Profile | thesis · paper · paper (anonymous review) · camera-ready · everything |
| Stage | `draft` never blocks · `submission` · `final` promotes warnings to errors |
| Venue | CHI · ASSETS · AutomotiveUI · IMWUT · TRF · MobileHCI · UIST · CHI PLAY · NeurIPS · ICLR · CVPR · AAAI |
| Verify refs | turns on the seven `BIO*` rules |
| Check automatically | run as soon as a project opens |

If the Overleaf project contains a `mechcheck.yaml`, it is read as well: rules
it disables stay quiet, severities and per-rule options apply, the project's
own vocabulary (`terminology:`) is enforced, and its profile, stage and venue
are adopted into the panel's controls. The panel says which file it used. It
is the same file the command line and CI read, so the extension and CI agree.

## Giving it to students

Unpacked installation is fine for a research group: send them the folder and
the four steps above. Chrome shows an "extensions in developer mode" warning on
each restart, which is cosmetic.

For a smoother experience, publishing to the Chrome Web Store costs a one-time
$5 developer registration and a review of a few days. Worth it if you hand this
to every student every semester; not worth it for five people.

## Keeping it in sync with the rest

`extension/engine.js` is **generated** from `browser/mechcheck.html`, so the
extension, the standalone page and (through the shared fixtures) the Python
version cannot drift apart:

```bash
node browser/build-extension.mjs     # after editing browser/mechcheck.html
```

The generated file is committed, so nobody needs to run this to install.

## Testing it without a live project

`extension/test-harness.html` fakes the `chrome.*` APIs, serves a small project
from a mocked `fetch`, and drives the real content script — the panel, the zip
reading, the filters, the Markdown export and the error path. Open
`extension/test-harness.built.html` (self-contained; produced by the build
script) in any browser. It reports 22 checks.

## What is verified, and what is not

Verified: the engine (290 Node checks), the zip reading, the panel rendering,
filtering and fixing in a real browser (22 harness checks), the manifest, and
the icons.

**Verified against a live Overleaf project** on 2026-08-28: the extension
injected, read the project, and reported exactly the findings the self-test
document was documented to produce at the time — every rule, every count.
(The documented figure has since grown with the rule set; see
[testing.md](testing.md) for the current one.)

The one thing outside anyone's control is that `/project/<id>/download/zip` is
Overleaf's own download URL rather than a public API, so a future change could
move it. If it ever fails, the panel says so explicitly rather than silently
reporting nothing, and the standalone HTML page still works as a fallback.
