from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.codex_app_apply_rrule import (
    _now_ms,
    _update_sqlite,
    _update_toml,
    main,
)


def _write_toml(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'version = 1\nid = "loopx"\nkind = "heartbeat"\n'
        'status = "ACTIVE"\nrrule = "FREQ=MINUTELY;INTERVAL=3"\n',
        encoding="utf-8",
    )


def _write_db(path: Path, *, rrule: str = "FREQ=MINUTELY;INTERVAL=3") -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            "CREATE TABLE automations ("
            "id TEXT PRIMARY KEY, name TEXT, prompt TEXT, status TEXT, "
            "next_run_at INTEGER, last_run_at INTEGER, cwds TEXT, rrule TEXT, "
            "model TEXT, reasoning_effort TEXT, created_at INTEGER, "
            "updated_at INTEGER, target_type TEXT, project_id TEXT)"
        )
        connection.execute(
            "INSERT INTO automations (id, name, prompt, status, cwds, rrule, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "loopx",
                "LoopX 旁路",
                "advance loopx-meta",
                "ACTIVE",
                "[]",
                rrule,
                _now_ms(),
                _now_ms(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _hint_payload(*, apply_needed: bool, ack_needed: bool = False) -> dict:
    return {
        "ok": True,
        "scheduler_hint": {
            "codex_app": {
                "recommended_rrule": (
                    "FREQ=MINUTELY;INTERVAL=5" if apply_needed else None
                ),
                "stateful_backoff": {
                    "apply_needed": apply_needed,
                    "ack_needed": ack_needed,
                    "current_rrule": "FREQ=MINUTELY;INTERVAL=3",
                },
                "ack_hint": (
                    {
                        "cli_args": [
                            "quota",
                            "scheduler-ack-current",
                            "--goal-id",
                            "loopx-meta",
                            "--applied-rrule",
                            "FREQ=MINUTELY;INTERVAL=5",
                            "--host-match-observed",
                            "--execute",
                        ]
                    }
                    if apply_needed or ack_needed
                    else None
                ),
            }
        },
    }


class _FakeCompleted:
    def __init__(self, payload: dict) -> None:
        self.returncode = 0
        self.stdout = json.dumps(payload)
        self.stderr = ""


def test_apply_updates_toml_db_and_runs_ack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    toml_path = tmp_path / "automations/loopx/automation.toml"
    db_path = tmp_path / "codex-dev.db"
    _write_toml(toml_path)
    _write_db(db_path)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        if "should-run" in command:
            return _FakeCompleted(_hint_payload(apply_needed=True))
        calls.append(command)
        return _FakeCompleted({"ok": True})

    monkeypatch.setattr("scripts.codex_app_apply_rrule.subprocess.run", fake_run)

    code = main(
        [
            "--automations-root",
            str(tmp_path / "automations"),
            "--db-path",
            str(db_path),
            "--loopx",
            "loopx",
        ]
    )

    assert code == 0
    assert 'rrule = "FREQ=MINUTELY;INTERVAL=5"' in toml_path.read_text(
        encoding="utf-8"
    )
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT rrule FROM automations WHERE id='loopx'"
        ).fetchone()
    finally:
        connection.close()
    assert row == ("FREQ=MINUTELY;INTERVAL=5",)
    assert calls and calls[0][0] == "loopx"
    assert any("scheduler-ack-current" in call for call in calls)
    backups = list(tmp_path.glob("codex-dev.db.bak-*"))
    assert len(backups) == 1


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    toml_path = tmp_path / "automations/loopx/automation.toml"
    db_path = tmp_path / "codex-dev.db"
    _write_toml(toml_path)
    _write_db(db_path)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return _FakeCompleted(_hint_payload(apply_needed=True))

    monkeypatch.setattr("scripts.codex_app_apply_rrule.subprocess.run", fake_run)

    code = main(
        [
            "--automations-root",
            str(tmp_path / "automations"),
            "--db-path",
            str(db_path),
            "--loopx",
            "loopx",
            "--dry-run",
        ]
    )

    assert code == 0
    assert 'rrule = "FREQ=MINUTELY;INTERVAL=3"' in toml_path.read_text(
        encoding="utf-8"
    )
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT rrule FROM automations WHERE id='loopx'"
        ).fetchone()
    finally:
        connection.close()
    assert row == ("FREQ=MINUTELY;INTERVAL=3",)
    assert not list(tmp_path.glob("codex-dev.db.bak-*"))
    assert all("scheduler-ack-current" not in call for call in calls)


def test_no_apply_needed_is_quiet_noop(tmp_path: Path, monkeypatch) -> None:
    toml_path = tmp_path / "automations/loopx/automation.toml"
    db_path = tmp_path / "codex-dev.db"
    _write_toml(toml_path)
    _write_db(db_path)
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return _FakeCompleted(_hint_payload(apply_needed=False, ack_needed=True))

    monkeypatch.setattr("scripts.codex_app_apply_rrule.subprocess.run", fake_run)

    code = main(
        [
            "--automations-root",
            str(tmp_path / "automations"),
            "--db-path",
            str(db_path),
            "--loopx",
            "loopx",
        ]
    )

    assert code == 0
    assert 'rrule = "FREQ=MINUTELY;INTERVAL=3"' in toml_path.read_text(
        encoding="utf-8"
    )
    assert not list(tmp_path.glob("codex-dev.db.bak-*"))
    assert any("scheduler-ack-current" in call for call in calls)


def test_update_toml_and_sqlite_helpers(tmp_path: Path) -> None:
    toml_path = tmp_path / "automation.toml"
    db_path = tmp_path / "store.db"
    _write_toml(toml_path)
    _write_db(db_path)

    _update_toml(toml_path, "FREQ=MINUTELY;INTERVAL=10")
    _update_sqlite(
        db_path,
        automation_id="loopx",
        rrule="FREQ=MINUTELY;INTERVAL=10",
        backup_path=tmp_path / "store.db.bak",
    )

    assert 'rrule = "FREQ=MINUTELY;INTERVAL=10"' in toml_path.read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "store.db.bak").exists()
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT rrule FROM automations WHERE id='loopx'"
        ).fetchone()
    finally:
        connection.close()
    assert row == ("FREQ=MINUTELY;INTERVAL=10",)
