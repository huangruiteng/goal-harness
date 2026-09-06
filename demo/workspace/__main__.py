"""Seed real, isolated LoopX state and serve the shipped Workspace over it."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from loopx.bootstrap import bootstrap_project
from loopx.configure_goal import configure_goal
from loopx.state_refresh import refresh_state_run
from loopx.todos import add_goal_todo, complete_goal_todo, update_goal_todo

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MARKER = ".workspace-story-demo.json"


def checked(result: dict) -> dict:
    if not result.get("ok"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def prepare(root: Path) -> dict:
    root = root.expanduser()
    if root.is_symlink():
        raise ValueError("Demo root must not be a symlink")
    root = root.resolve()
    marker = root / MARKER
    if marker.exists():
        manifest = json.loads(marker.read_text())
        if manifest.get("schema_version") != "workspace_story_demo_v2":
            raise ValueError("Unrecognized demo manifest")
        if manifest.get("root") != str(root) or manifest.get("registry") != str(
            root / "registry.json"
        ):
            raise ValueError("Demo manifest does not belong to this directory")
        if not (root / "registry.json").is_file():
            raise ValueError("Demo registry is missing; use a new empty directory")
        return manifest
    if root.exists() and any(root.iterdir()):
        raise ValueError(
            "Choose a new or empty directory; existing work is never overwritten"
        )
    root.mkdir(parents=True, exist_ok=True)
    runtime = root / "runtime"
    registry = root / "registry.json"
    catalog = json.loads((HERE / "stories.json").read_text())
    manifest = {
        "schema_version": "workspace_story_demo_v2",
        "notice": catalog["notice"],
        "root": str(root),
        "registry": str(registry),
        "goals": [],
    }
    for story in catalog["stories"]:
        project = root / "projects" / story["id"]
        project.mkdir(parents=True)
        (project / "GOAL.md").write_text(
            f"# {story['title']}\n\n{story['objective']}\n\n{catalog['notice']}\n"
        )
        checked(
            bootstrap_project(
                project=project,
                registry_path=registry,
                runtime_root=runtime,
                goal_id=story["id"],
                display_name=story["title"],
                objective=story["objective"],
                domain="workspace-demo",
                role="controller",
                parent_goal_id=None,
                state_file=None,
                goal_doc=Path("GOAL.md"),
                adapter_kind="workspace_story_demo_v2",
                adapter_status="connected-read-only",
                next_probe=None,
                spawn_allowed=False,
                max_children=0,
                allowed_domains=[],
                write_scope=[],
                onboarding_scan_enabled=False,
                codex_app_heartbeat="no",
                force=False,
                dry_run=False,
                sync_global=False,
            )
        )
        checked(
            configure_goal(
                registry_path=registry,
                goal_id=story["id"],
                registered_agents=story["agents"],
                execute=True,
            )
        )
        (project / "BRIEF.md").write_text(f"# {story['title']}\n\n{story['brief']}\n")
        with (project / "working-table.csv").open("w", newline="") as table:
            writer = csv.writer(table)
            writer.writerow(["item", "amount"])
            writer.writerows(story["rows"])
        calculation = {
            "provenance": catalog["notice"],
            "inputs": story["rows"],
            "sum": sum(row[1] for row in story["rows"]),
            "row_count": len(story["rows"]),
        }
        if "budget_limit" in story:
            calculation["contingency"] = story["budget_limit"] - calculation["sum"]
        if story["id"] == "research-brief":
            calculation["operating_cost_sensitivity"] = [
                {
                    "heat_kwh": heat,
                    "tariff": tariff,
                    "efficiency": efficiency,
                    "annual_cost": round(heat / efficiency * tariff, 2),
                }
                for heat in [6000, 12000, 18000]
                for tariff in [0.2, 0.3, 0.4]
                for efficiency in [2.5, 3.0, 3.5]
            ]
        (project / "calculations.json").write_text(json.dumps(calculation, indent=2))
        gates = {}
        for decision in story["gates"]:
            gate = checked(
                add_goal_todo(
                    registry_path=registry,
                    runtime_root_arg=str(runtime),
                    goal_id=story["id"],
                    role="user",
                    task_class="user_gate",
                    action_kind="approve",
                    blocks_agent=decision["agent"],
                    text="[P0] " + decision["title"],
                )
            )
            gates[decision["key"]] = {
                "todo_id": gate["todo_id"],
                "agent": decision["agent"],
            }
        todos = []
        ids = {"gate:" + key: value["todo_id"] for key, value in gates.items()}
        for task in story["tasks"]:
            owner, status, title = task["agent"], task["status"], task["title"]
            dependency = ids[task["after"]] if task.get("after") else None
            result = checked(
                add_goal_todo(
                    registry_path=registry,
                    runtime_root_arg=str(runtime),
                    goal_id=story["id"],
                    role="agent",
                    text="[P1] " + title,
                    task_class="advancement_task",
                    action_kind="prepare",
                    task_domain=task["phase"].lower().replace(" ", "-"),
                    claimed_by=owner,
                    status="open" if status == "done" else status,
                    resume_when="todo_done:" + dependency
                    if status == "deferred"
                    else None,
                    note=f"Phase: {task['phase']}. Dependency: {dependency or 'none'}. See BRIEF.md and calculations.json.",
                )
            )
            todo_id = result["todo_id"]
            ids[task["key"]] = todo_id
            if status == "done":
                checked(
                    complete_goal_todo(
                        registry_path=registry,
                        runtime_root_arg=str(runtime),
                        goal_id=story["id"],
                        todo_id=todo_id,
                        agent_id=owner,
                        evidence="Scenario replay checkpoint; BRIEF.md, working-table.csv and calculations.json retain the planning inputs. No live execution receipt claimed.",
                        no_followup=True,
                    )
                )
            todos.append({**task, "todo_id": todo_id})
        monitors = []
        for owner, title, cadence, target in story["monitors"]:
            monitor = checked(
                add_goal_todo(
                    registry_path=registry,
                    runtime_root_arg=str(runtime),
                    goal_id=story["id"],
                    role="agent",
                    text="[P2] " + title,
                    task_class="continuous_monitor",
                    action_kind="watch",
                    claimed_by=owner,
                    monitor_metadata={
                        "target_key": target,
                        "cadence": cadence,
                        "watch_only": True,
                        "next_due_at": (
                            datetime.now(timezone.utc) + timedelta(days=1)
                        ).isoformat(),
                    },
                )
            )
            monitors.append(monitor["todo_id"])
        (project / "DELIVERY-PLAN.md").write_text(
            "# Delivery plan\n\n"
            + "\n".join(
                f"- **{t['phase']} / {t['agent']} / {t['status']}** — {t['title']}"
                + (f" (after {t['after']})" if t.get("after") else "")
                for t in story["tasks"]
            )
            + "\n"
        )
        checked(
            refresh_state_run(
                registry_path=registry,
                runtime_root_override=str(runtime),
                goal_id=story["id"],
                project=project,
                state_file=None,
                classification="workspace_demo_prepared",
                recommended_action="Inspect the example work, review the owner decision, and compare independent Agent lanes.",
                agent_id=story["agents"][0],
                progress_scope="agent_lane",
                dry_run=False,
                sync_global=False,
            )
        )
        manifest["goals"].append(
            {
                "id": story["id"],
                "title": story["title"],
                "todos": todos,
                "gates": gates,
                "monitors": monitors,
            }
        )
    marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "serve", "advance"])
    parser.add_argument(
        "--story", choices=["community-day", "research-brief", "neighborhood-site"]
    )
    parser.add_argument(
        "--decision", help="Decision key; defaults to the first decision in the story"
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="A new empty directory; omitted uses a temporary directory",
    )
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--_isolated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = (
        args.root or Path(tempfile.mkdtemp(prefix="loopx-workspace-demo-"))
    ).expanduser()
    if root.is_symlink():
        parser.error("Demo root must not be a symlink")
    root = root.resolve()
    if args.command == "serve" and not args._isolated:
        # Isolate machine settings, host discovery and credentials from the user's home.
        home = root / "home"
        manifest = prepare(root)
        home.mkdir(exist_ok=True)
        env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
        }
        env.update(
            HOME=str(home), CODEX_HOME=str(home / ".codex"), PYTHONPATH=str(REPO)
        )
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{args.port}/chat/",
                    "notice": manifest["notice"],
                }
            ),
            flush=True,
        )
        raise SystemExit(
            subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "demo.workspace",
                    "serve",
                    "--root",
                    str(root),
                    "--port",
                    str(args.port),
                    "--_isolated",
                ],
                cwd=REPO,
                env=env,
            )
        )
    manifest = prepare(root)
    if args.command == "advance":
        if not args.story:
            parser.error("advance requires --story")
        story = next(s for s in manifest["goals"] if s["id"] == args.story)
        registry = root / "registry.json"
        decision_key = args.decision or next(iter(story["gates"]))
        if decision_key not in story["gates"]:
            parser.error(f"Unknown decision; choose one of {list(story['gates'])}")
        decision = story["gates"][decision_key]
        checked(
            complete_goal_todo(
                registry_path=registry,
                runtime_root_arg=str(root / "runtime"),
                goal_id=args.story,
                todo_id=decision["todo_id"],
                role="user",
                decision_outcome="approve",
                agent_id=decision["agent"],
                evidence="Illustrative demo decision replay; no external action authorized.",
                no_followup=True,
            )
        )
        for todo in story["todos"]:
            if (
                todo["status"] == "blocked"
                and todo.get("after") == "gate:" + decision_key
            ):
                checked(
                    update_goal_todo(
                        registry_path=registry,
                        runtime_root_arg=str(root / "runtime"),
                        goal_id=args.story,
                        todo_id=todo["todo_id"],
                        status="open",
                        agent_id=todo["agent"],
                        reason="Decision replay resolved this local blocker.",
                    )
                )
        print(
            json.dumps(
                {
                    "advanced": args.story,
                    "decision": decision_key,
                    "external_effects": False,
                }
            )
        )
        return
    if args.command == "prepare":
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    from loopx.chat_server import serve_chat

    serve_chat(
        registry_path=root / "registry.json",
        runtime_root_override=root / "runtime",
        scan_roots=[root],
        port=args.port,
        assets_dir=REPO / "loopx/web/chat",
        codex_bin="loopx-demo-no-agent",
        claude_bin="loopx-demo-no-agent",
        lark_cli_bin="loopx-demo-no-lark",
    )


if __name__ == "__main__":
    main()
