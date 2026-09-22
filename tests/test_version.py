"""One version number, in three files that must agree.

The package, the installable metadata and the Chrome extension each carry
their own copy, and they drifted: ``pyproject.toml`` moved to 0.2.0 while
``mechcheck/__init__.py`` stayed at 0.1.0, so the extension reported one
version, the User-Agent sent to Crossref another, and pip a third. Nothing
broke, which is why nobody noticed.

There is no build step that could derive one from the others -- the
extension is loaded unpacked from the repository, and the package must
install with no dependencies -- so the agreement is asserted instead.
"""

from __future__ import annotations

import json
import os
import re

import mechcheck

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject_version() -> str:
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
        for line in handle:
            match = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
            if match:
                return match.group(1)
    raise AssertionError("pyproject.toml has no version")


def _manifest_version() -> str:
    with open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8") as handle:
        return json.load(handle)["version"]


def test_the_three_versions_agree():
    assert mechcheck.__version__ == _pyproject_version() == _manifest_version()


def test_the_version_is_one_chrome_will_accept():
    # Chrome takes one to four dot-separated integers, each 0-65535, and
    # refuses to load the extension otherwise -- with the folder already
    # picked, which is a confusing place to find out.
    parts = _manifest_version().split(".")
    assert 1 <= len(parts) <= 4
    assert all(part.isdigit() and 0 <= int(part) <= 65535 for part in parts)
    assert all(part == "0" or not part.startswith("0") for part in parts)
