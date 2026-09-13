"""``python -m mechcheck`` runs the same entry point as the ``mechcheck`` command.

This matters most on Windows, where pip's Scripts directory is often not on
PATH and ``mechcheck`` is "not recognized" even though the install succeeded.
"""

from __future__ import annotations

import sys

from mechcheck.cli import main

if __name__ == "__main__":
    sys.exit(main())
