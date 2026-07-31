#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

GOAL_ID = "issue-fix-portfolio-smoke"
AGENT_ID = "issue-fix-portfolio-agent"

# A clearly fixture repository so the smoke never implies real issue state and
# never touches the network (--fetch-metadata is off).
REPO_LABEL = "example-owner/example-repo"
ISSUE_NUMBERS = "101,102,103"


def run_cli(registry: Path, args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--registry",
            str(registry),
            "--format",
            "json",
            *args,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(result.stdout)


def write_fixture(root: Path) -> tuple[Path, Path]:
    project = root / "project"
    project.mkdir()
    state_file = project / "ACTIVE_GOAL_STATE.md"
    state_file.write_text(
        "# Issue Fix Portfolio Smoke\n\n"
        "## User Todo / Owner Review Reading Queue\n\n"
        "## Agent Todo\n",
        encoding="utf-8",
    )
    registry = root / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(project),
                        "state_file": str(state_file),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return project, registry


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _boundary_clean(flags: dict[str, Any]) -> bool:
    return all(not value for value in flags.values())


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project, registry = write_fixture(root)

        read_only = run_cli(
            registry,
            [
                "issue-fix",
                "portfolio-plan",
                "--repo",
                REPO_LABEL,
                "--issues",
                ISSUE_NUMBERS,
            ],
        )
        _assert(bool(read_only.get("ok")), "read-only portfolio packet must be ok")
        _assert(
            read_only.get("schema_version") == "issue_fix_portfolio_packet_v0",
            "read-only packet schema_version must be issue_fix_portfolio_packet_v0",
        )
        _assert(
            read_only.get("candidate_count") == 3,
            "read-only packet must list 3 candidates",
        )
        chain = read_only.get("chain") or []
        _assert(len(chain) == 3, "read-only packet must list 3 chain entries")
        _assert(
            chain[0]["status"] == "open"
            and chain[0]["resume_depends_on_order"] is None
            and chain[0]["resume_when_pattern"] is None,
            "issue 1 must be open with no resume dependency",
        )
        _assert(
            chain[1]["status"] == "deferred"
            and chain[1]["resume_depends_on_order"] == 1
            and chain[1]["resume_when_pattern"] == "todo_done:{previous_issue_todo_id}",
            "issue 2 must be deferred behind issue 1's todo_done",
        )
        _assert(
            chain[2]["status"] == "deferred"
            and chain[2]["resume_depends_on_order"] == 2,
            "issue 3 must be deferred behind issue 2's todo_done",
        )
        _assert(
            not read_only.get("todo_write_performed"),
            "read-only packet must not perform todo writes",
        )
        _assert(
            _boundary_clean(read_only.get("boundary_flags") or {}),
            "read-only packet must stay body-free and path-free",
        )

        applied = run_cli(
            registry,
            [
                "issue-fix",
                "portfolio-plan",
                "--repo",
                REPO_LABEL,
                "--issues",
                ISSUE_NUMBERS,
                "--execute",
                "--goal-id",
                GOAL_ID,
                "--agent-id",
                AGENT_ID,
                "--project",
                str(project),
            ],
        )
        _assert(bool(applied.get("ok")), "apply packet must be ok")
        _assert(
            applied.get("todo_write_performed") is True,
            "apply packet must report todo_write_performed",
        )
        todos = applied.get("applied_todos") or []
        _assert(len(todos) == 3, "apply must write 3 chained todos")
        todo_ids = [entry.get("todo_id") for entry in todos]
        _assert(
            len({tid for tid in todo_ids if tid}) == 3,
            "each applied todo must have a unique todo_id",
        )

        first = todos[0]
        _assert(
            first["status"] == "open"
            and first["claimed_by"] == AGENT_ID
            and first["resume_when"] is None,
            "issue 1 todo must be open, claimed by the agent, and have no resume_when",
        )

        for index in (1, 2):
            entry = todos[index]
            previous = todos[index - 1]
            expected_resume = f"todo_done:{previous['todo_id']}"
            _assert(
                entry["status"] == "deferred"
                and entry["resume_when"] == expected_resume,
                f"issue {index + 1} todo must be deferred behind "
                f"{previous['todo_id']!r} via {expected_resume!r}, got status="
                f"{entry.get('status')!r} resume_when={entry.get('resume_when')!r}",
            )
            _assert(
                entry["action_kind"] == "issue_fix_portfolio_advancement",
                "applied todos must use the issue_fix_portfolio_advancement action kind",
            )
            _assert(
                bool(entry["task_repository"]),
                "applied todos must carry a task_repository pin",
            )

        _assert(
            _boundary_clean(applied.get("boundary_flags") or {}),
            "apply packet must keep the public/private boundary clean",
        )

        # The state file must persist the deferred chain so the heartbeat can
        # project resume readiness on a later bounded turn.
        state_text = (project / "ACTIVE_GOAL_STATE.md").read_text(encoding="utf-8")
        _assert(
            "resume_when=" in state_text and "todo_done:" in state_text,
            "state file must persist resume_when todo_done linkage for deferred issues",
        )
        _assert(
            state_text.count("issue_fix_portfolio_advancement") == 3,
            "state file must record all three advancement todos",
        )

        # A list/repo URL must auto-enumerate into candidate issues, and with
        # --execute but no --goal-id/--agent-id the single registered goal+agent
        # must be auto-resolved so a user can type just the URL.
        override_path = root / "enum-override.json"
        override_path.write_text("[201,202]", encoding="utf-8")
        enumerated = run_cli(
            registry,
            [
                "issue-fix",
                "portfolio-plan",
                "--url",
                "https://github.com/example-owner/example-repo/issues",
                "--enumerated-issues-json",
                str(override_path),
                "--max-issues",
                "8",
            ],
        )
        _assert(bool(enumerated.get("ok")), "enumerated portfolio packet must be ok")
        enum_log = (enumerated.get("enumeration") or {}).get("enumerated_repos") or []
        _assert(len(enum_log) == 1, "enumeration log must record the one repo URL")
        _assert(
            enum_log[0]["source"] == "caller_override"
            and enum_log[0]["numbers"] == [201, 202],
            "enumeration override must record the curated numbers in order",
        )
        enum_candidates = enumerated.get("candidates") or []
        _assert(
            [c.get("number") for c in enum_candidates] == [201, 202],
            "list URL must expand into one candidate per enumerated issue",
        )

        auto_applied = run_cli(
            registry,
            [
                "issue-fix",
                "portfolio-plan",
                "--url",
                "https://github.com/example-owner/example-repo/issues",
                "--enumerated-issues-json",
                str(override_path),
                "--max-issues",
                "8",
                "--execute",
                "--project",
                str(project),
            ],
        )
        _assert(bool(auto_applied.get("ok")), "auto-resolved apply must be ok")
        auto_todos = auto_applied.get("applied_todos") or []
        _assert(len(auto_todos) == 2, "auto-resolved apply must write 2 todos")
        _assert(
            auto_todos[0]["status"] == "open"
            and auto_todos[0]["claimed_by"] == AGENT_ID,
            "auto-resolved apply must claim issue 1 with the single registered agent",
        )
        _assert(
            auto_todos[1]["status"] == "deferred"
            and auto_todos[1]["resume_when"]
            == f"todo_done:{auto_todos[0]['todo_id']}",
            "auto-resolved apply must still chain issue 2 behind issue 1",
        )

    print("issue-fix-portfolio-smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
