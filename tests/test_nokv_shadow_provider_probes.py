"""Keep the RFC shared-goal provider evidence command green.

``examples/nokv-shadow-provider/README.md`` names
``python3 examples/nokv-shadow-provider/probes.py contract`` as the merge
evidence for the coordination contract. The probes import the LoopX
durable-completion seam, so a lifecycle contract change can silently turn that
evidence red; this test runs the command exactly as documented.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROBES = REPOSITORY_ROOT / "examples" / "nokv-shadow-provider" / "probes.py"
LIVE_E2E = REPOSITORY_ROOT / "examples" / "nokv-shadow-provider" / "live_e2e.py"

EXPECTED_TAGS = (
    "contract.bootstrap_and_preconditions",
    "contract.a_success_b_advance_replay_a",
    "contract.operation_identity",
    "contract.competing_claims",
    "contract.crash_windows_and_ambiguity",
    "contract.version_domains_and_retain_all",
    "contract.nokv_adapter_exception_mapping",
    "contract.nokv_fresh_client_failure_is_typed",
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


def test_live_nokv_provider_handles_use_typed_composition_factory() -> None:
    """Keep fallible SDK construction inside the adapter-owned boundary."""

    tree = ast.parse(LIVE_E2E.read_text(encoding="utf-8"), filename=str(LIVE_E2E))
    direct_import_lines: list[int] = []
    direct_names: set[str] = set()
    factory_names: set[str] = set()
    provider_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "provider":
            for alias in node.names:
                binding = alias.asname or alias.name
                if alias.name == "NoKVCoordinationProvider":
                    direct_import_lines.append(node.lineno)
                    direct_names.add(binding)
                elif alias.name == "open_nokv_coordination_provider":
                    factory_names.add(binding)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "provider":
                    provider_modules.add(alias.asname or alias.name)

    direct_call_lines: list[int] = []
    factory_call_lines: list[int] = []
    eager_factory_argument_lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_factory_call = False
        if isinstance(node.func, ast.Name):
            if node.func.id in direct_names:
                direct_call_lines.append(node.lineno)
            if node.func.id in factory_names:
                factory_call_lines.append(node.lineno)
                is_factory_call = True
        elif isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if (
                node.func.value.id in provider_modules
                and node.func.attr == "NoKVCoordinationProvider"
            ):
                direct_call_lines.append(node.lineno)
            if (
                node.func.value.id in provider_modules
                and node.func.attr == "open_nokv_coordination_provider"
            ):
                factory_call_lines.append(node.lineno)
                is_factory_call = True

        if is_factory_call:
            client_factory = node.args[0] if node.args else None
            if client_factory is None:
                client_factory = next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "client_factory"
                    ),
                    None,
                )
            if client_factory is None or isinstance(client_factory, ast.Call):
                eager_factory_argument_lines.append(node.lineno)

    assert not direct_import_lines, direct_import_lines
    assert not direct_call_lines, direct_call_lines
    assert factory_call_lines, "live NoKV composition must use the typed factory"
    assert not eager_factory_argument_lines, eager_factory_argument_lines
