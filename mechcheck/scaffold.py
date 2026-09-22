"""``mechcheck init``: drop the config, the workflow and the .sty into a project.

Adoption friction is the thing that decides whether a checker gets used, so
this writes working files rather than telling somebody to read documentation.
"""

from __future__ import annotations

import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

CONFIG_TEMPLATE = """# mechcheck configuration
#
# Full rule list:            mechcheck rules
# What one rule means:       mechcheck explain FIG003
# Silence one line:          % mechcheck: off FIG003 -- reason
# Silence a whole file:      % mechcheck: off-file BIO005 -- reason
#
# Keep this file inside the small YAML subset mechcheck documents (two-space
# indent, simple key: value, "- item" lists) so it stays readable by every part
# of the toolchain.

profile: {profile}      # thesis | paper | paper-anonymous | camera-ready | all
stage: submission       # draft (nothing blocks) | submission | final (warnings become errors)
{venue_line}
language: en
fail_on: error          # exit non-zero at this severity

# Contact address for the Crossref/OpenAlex "polite pool". Being identifiable
# gets you better rate limits, and is the courteous thing to do.
mailto: ''

disable: []
enable: []

severity: {{}}

# One name per concept. mechcheck reports a document that uses two of them
# (TRM001); naming the one this project uses makes it a rule, and one that
# `mechcheck fix .` applies for you. `mechcheck terms .` prints what your
# document actually calls things, ready to paste in here.
#
# terminology:
#   - prefer: automated vehicle
#     over: [self-driving car, autonomous vehicle, driverless car]
#   - variants: [participant, test person]

rules:
  ABB004:
    # Abbreviations that need no expansion in your field.
    ignore:
      - HMI
      - ADAS
      - AV
  STY012:
    max_words: 45
"""

WORKFLOW = """name: mechcheck

# Runs on every push, and on a schedule so a thesis that has gone quiet still
# gets checked. See docs/overleaf-setup.md for wiring this to an Overleaf
# project (Overleaf's GitHub sync is manual, so the mirror job matters).

on:
  push:
  pull_request:
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      # mechcheck is not on PyPI: install it straight from its repository.
      - name: Install mechcheck
        run: pip install "git+https://github.com/M-Colley/mechcheck"

      # Bibliographic metadata barely changes, so caching the API responses
      # keeps the reference checks close to free on repeat runs.
      - name: Cache reference lookups
        uses: actions/cache@v4
        with:
          path: ~/.cache/mechcheck
          key: mechcheck-refs-${{ hashFiles('**/*.bib') }}
          restore-keys: mechcheck-refs-

      - name: Run the mechanical checks
        run: |
          mechcheck check . \\
            --format github \\
            --also markdown=mechcheck-report.md \\
            --also sarif=mechcheck.sarif

      - name: Publish the summary
        if: always()
        run: cat mechcheck-report.md >> "$GITHUB_STEP_SUMMARY"

      - name: Upload findings to code scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: mechcheck.sarif
        continue-on-error: true
"""


def init_project(path: str, profile: str = "thesis", venue: str | None = None,
                 with_ci: bool = False, with_sty: bool = False, force: bool = False) -> int:
    root = os.path.abspath(path)
    if not os.path.isdir(root):
        print(f"mechcheck: not a directory: {root}")
        return 2

    written, skipped = [], []

    # A thesis is not submitted to a venue; anything else gets the default.
    if not venue:
        venue = None if profile == "thesis" else "chi"
    venue_line = (f"venue: {venue}" if venue else "venue: null") + \
        "           # chi | assets | autoui | mobilehci | uist | chiplay | imwut | trf | neurips | iclr | cvpr | aaai"
    config = CONFIG_TEMPLATE.format(profile=profile, venue_line=venue_line)
    _write(os.path.join(root, "mechcheck.yaml"), config, force, written, skipped)

    if with_ci:
        _write(os.path.join(root, ".github", "workflows", "mechcheck.yml"),
               WORKFLOW, force, written, skipped)

    if with_sty:
        source = os.path.join(REPO, "latex", "mechcheck.sty")
        target = os.path.join(root, "mechcheck.sty")
        if os.path.isfile(source):
            if os.path.exists(target) and not force:
                skipped.append(target)
            else:
                shutil.copyfile(source, target)
                written.append(target)
        else:
            print(f"mechcheck: could not find {source}")

    for p in written:
        print(f"wrote    {os.path.relpath(p, root)}")
    for p in skipped:
        print(f"skipped  {os.path.relpath(p, root)} (exists; use --force)")

    if written:
        print("\nNext:")
        print("  mechcheck check .            # see where the document stands")
        print("  mechcheck baseline .         # freeze today's findings, enforce from here")
        if with_sty:
            print("  \\usepackage{mechcheck}       # add to your preamble for compile-time checks")
    return 0


def _write(path: str, content: str, force: bool, written: list, skipped: list) -> None:
    if os.path.exists(path) and not force:
        skipped.append(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    written.append(path)
