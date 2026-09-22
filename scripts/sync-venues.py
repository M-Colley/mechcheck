"""Mirror the venue packs into the single-file browser page.

``mechcheck/venues/*.yaml`` is the source of truth: the command line reads it
directly. The page is one HTML file that has to work from a local disk with
no server, so it cannot read those files and carries a copy instead.

That copy is generated here rather than maintained by hand, and
``browser/test-engine.mjs`` compares the two pack by pack afterwards, so the
two cannot drift apart unnoticed. Run this after editing any pack:

    python scripts/sync-venues.py

It rewrites the ``const VENUES = {...}`` block in browser/mechcheck.html and
says whether anything changed. Run ``node browser/build-extension.mjs``
afterwards to carry the change into the extension.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mechcheck import minyaml                                    # noqa: E402
from mechcheck.config import VENUE_DIR, available_venues         # noqa: E402

PAGE = ROOT / "browser" / "mechcheck.html"
START = "/* Venue packs, mirrored from mechcheck/venues/*.yaml."
END = "\nfunction globMatch("

HEADER = """/* Venue packs, mirrored from mechcheck/venues/*.yaml.
   The page is one file and cannot read them off disk, so it carries a
   copy. The copy is GENERATED -- edit the YAML, then run
   `python scripts/sync-venues.py` -- and browser/test-engine.mjs compares
   the two pack by pack, so they cannot drift apart unnoticed.
   Each pack keeps its own `verified` date, `source_url` and the
   `uncertain` list of what could not be confirmed. */
"""


def load_packs() -> dict:
    """Parse every pack with the restricted parser the page also uses."""
    packs = {}
    for name in available_venues():
        raw = pathlib.Path(VENUE_DIR, name + ".yaml").read_text(encoding="utf-8")
        packs[name] = minyaml.loads_builtin(raw)
    return packs


def render(packs: dict) -> str:
    # json.dumps already produces the shape the page uses: two-space contents
    # with the closing brace at column 0.
    return HEADER + "const VENUES = " + json.dumps(
        packs, indent=2, ensure_ascii=False, default=str) + ";\n"


def main() -> int:
    import re

    packs = load_packs()
    text = PAGE.read_text(encoding="utf-8")
    try:
        start = text.index(START)
        end = text.index(END, start)
    except ValueError:
        print("could not find the VENUES block in browser/mechcheck.html", file=sys.stderr)
        return 1
    closing = None
    for m in re.finditer(r"^[ \t]*\};[ \t]*\n", text[start:end], re.MULTILINE):
        closing = m                       # the last one before globMatch
    if closing is None:
        print("could not find the end of the VENUES block", file=sys.stderr)
        return 1
    tail_start = start + closing.end()

    block = render(packs)
    if text[start:tail_start] == block:
        print(f"browser/mechcheck.html is already in sync ({len(packs)} packs)")
        return 0
    PAGE.write_text(text[:start] + block + text[tail_start:], encoding="utf-8", newline="")
    print(f"synced {len(packs)} venue packs into browser/mechcheck.html: "
          f"{', '.join(sorted(packs))}")
    print("now run: node browser/build-extension.mjs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
