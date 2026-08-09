#!/usr/bin/env python3
"""Apply a LoopX scheduler-hint RRULE to the Codex App automation store.

Fallback host bridge for hosts where the Codex App does not expose
``automation_update``. The script:

1. reads ``loopx quota should-run`` and its ``scheduler_hint.codex_app``;
2. when ``stateful_backoff.apply_needed=true`` and ``recommended_rrule`` is
   present, backs up the Codex App automation SQLite database, updates both
   the automation TOML and the ``automations`` row to the recommended RRULE;
3. runs the bound ``ack_hint.cli_args`` so LoopX persists the reset token and
   progression index.

The script is public-safe: it carries no credentials and all host paths can be
overridden for tests or alternate installations.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_scheduler_hint(
    *,
    loopx: str,
    registry: Path,
    goal_id: str,
    agent_id: str,
    turn_instance_id: str,
    capabilities: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    command = [
        loopx,
        "--format",
        "json",
        "--registry",
        str(registry),
        "quota",
        "should-run",
        "--goal-id",
        goal_id,
        "--agent-id",
        agent_id,
        "--codex-app",
        "--turn-instance-id",
        turn_instance_id,
    ]
    for capability in capabilities:
        command.extend(["--available-capability", capability])
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"loopx should-run failed ({completed.returncode}): "
            f"{completed.stderr[-500:]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"loopx should-run returned invalid JSON: {exc}") from exc
    hint = payload.get("scheduler_hint", {})
    codex_app = hint.get("codex_app", {})
    if not isinstance(codex_app, dict):
        codex_app = {}
    stateful = codex_app.get("stateful_backoff", {})
    if not isinstance(stateful, dict):
        stateful = {}
    return codex_app, stateful


def _update_toml(toml_path: Path, rrule: str) -> None:
    text = toml_path.read_text(encoding="utf-8")
    pattern = re.compile(r'^rrule\s*=\s*".*?"', re.MULTILINE)
    if not pattern.search(text):
        raise SystemExit(f"automation TOML has no rrule field: {toml_path}")
    toml_path.write_text(
        pattern.sub(f'rrule = "{rrule}"', text),
        encoding="utf-8",
    )


def _update_sqlite(
    db_path: Path,
    *,
    automation_id: str,
    rrule: str,
    backup_path: Path | None,
) -> None:
    if backup_path is not None:
        if not db_path.exists():
            raise SystemExit(f"automation SQLite does not exist: {db_path}")
        connection = sqlite3.connect(str(db_path))
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.backup(sqlite3.connect(str(backup_path)))
        finally:
            connection.close()
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        cursor = connection.execute(
            "UPDATE automations SET rrule=?, updated_at=? WHERE id=?",
            (rrule, _now_ms(), automation_id),
        )
        connection.commit()
        if cursor.rowcount != 1:
            raise SystemExit(
                f"automation row not found or not updated in {db_path}: "
                f"{automation_id}"
            )
    finally:
        connection.close()


def _run_ack(loopx: str, ack_args: list[str]) -> None:
    completed = subprocess.run(
        [loopx, *ack_args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"loopx scheduler ACK failed ({completed.returncode}): "
            f"{completed.stderr[-500:]}"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply the LoopX scheduler-hint RRULE to the Codex App automation "
            "store (TOML + SQLite) and run the bound ACK."
        )
    )
    parser.add_argument("--goal-id", default="loopx-meta")
    parser.add_argument("--agent-id", default="codex-side-bypass")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path.home() / ".codex/loopx/registry.global.json",
    )
    parser.add_argument("--automation-id", default="loopx")
    parser.add_argument(
        "--automations-root",
        type=Path,
        default=Path.home() / ".codex/automations",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.home() / ".codex/sqlite/codex-dev.db",
    )
    parser.add_argument("--loopx", default="loopx")
    parser.add_argument(
        "--capability",
        action="append",
        default=["network", "external_evidence_poll"],
    )
    parser.add_argument(
        "--turn-instance-id",
        default=f"apply-rrule-{_now_ms()}",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    codex_app, stateful = _load_scheduler_hint(
        loopx=args.loopx,
        registry=args.registry,
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        turn_instance_id=args.turn_instance_id,
        capabilities=args.capability,
    )
    apply_needed = stateful.get("apply_needed") is True
    rrule = codex_app.get("recommended_rrule") or stateful.get("current_rrule")
    ack_hint = codex_app.get("ack_hint", {})
    ack_args = ack_hint.get("cli_args") if isinstance(ack_hint, dict) else None
    toml_path = args.automations_root / args.automation_id / "automation.toml"

    if not apply_needed:
        print(
            f"no apply needed (apply_needed=false); rrule={rrule or 'unknown'}; "
            f"ack_needed={stateful.get('ack_needed') is True}"
        )
        if (
            stateful.get("ack_needed") is True
            and isinstance(ack_args, list)
            and not args.dry_run
        ):
            _run_ack(args.loopx, ack_args)
        return 0
    if not rrule:
        raise SystemExit(
            "apply_needed=true but no recommended_rrule/current_rrule was projected"
        )
    if not isinstance(ack_args, list):
        raise SystemExit("apply_needed=true but no ack_hint.cli_args was projected")

    backup_path = (
        Path(str(args.db_path) + f".bak-{time.strftime('%Y%m%dT%H%M%S')}")
        if not args.dry_run
        else None
    )
    print(f"apply rrule={rrule}")
    print(f"toml={toml_path}")
    print(f"db={args.db_path}")
    print(f"backup={backup_path or 'none (dry-run)'}")
    print(f"ack_args={ack_args}")
    if args.dry_run:
        print("dry-run: no writes performed")
        return 0

    _update_toml(toml_path, rrule)
    _update_sqlite(
        args.db_path,
        automation_id=args.automation_id,
        rrule=rrule,
        backup_path=backup_path,
    )
    _run_ack(args.loopx, ack_args)
    print(f"applied {rrule} and ACKed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
