"""Keep the RFC shared-goal provider evidence command green.

``examples/nokv-shadow-provider/README.md`` names
``python3 examples/nokv-shadow-provider/probes.py contract`` as the merge
evidence for the coordination contract. The probes import the LoopX
durable-completion seam, so a lifecycle contract change can silently turn that
evidence red; this test runs the command exactly as documented.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROBES = REPOSITORY_ROOT / "examples" / "nokv-shadow-provider" / "probes.py"

EXPECTED_TAGS = (
    "contract.bootstrap_and_preconditions",
    "contract.a_success_b_advance_replay_a",
    "contract.operation_identity",
    "contract.competing_claims",
    "contract.crash_windows_and_ambiguity",
    "contract.version_domains_and_retain_all",
    "contract.nokv_adapter_exception_mapping",
    "contract.durable_completion_projection",
    "contract.durable_completion_fail_closed",
)


def test_contract_probes_pass_as_documented() -> None:
    completed = subprocess.run(
        [sys.executable, str(PROBES), "contract"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    tags = [row["probe"] for row in rows]
    assert tags == [*EXPECTED_TAGS, "contract.summary"], tags
    assert all(row["ok"] is True for row in rows)
    assert rows[-1]["probes"] == len(EXPECTED_TAGS)
