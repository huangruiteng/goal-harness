#!/usr/bin/env python3
"""Run the shared-goal-authority E2E stage ladder against this checkout.

Thin entry point: the row registry, runners, report, and exit policy live in
``loopx.control_plane.testing.authority_e2e_ladder``. See README.md next to
this file for rows, gates, environment variables, and the exit policy.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.testing.authority_e2e_ladder import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
