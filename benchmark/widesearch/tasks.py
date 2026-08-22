"""WideSearch task data preparation and per-run workspace isolation.

Follows the practice contract in README.md: every run gets a fresh workspace so
a stale final_answer.md can never be mistaken for the current run's output.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


def load_raw_rows(raw: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in raw.open(encoding="utf-8")
        if line.strip()
    ]


def resolve_case(raw: Path, case_id: str) -> dict:
    row = next(
        (r for r in load_raw_rows(raw) if r["instance_id"] == case_id),
        None,
    )
    if row is None:
        raise KeyError(f"unknown instance_id: {case_id}")
    return row


def prepare_case(*, raw: Path, gold_dir: Path, cases_root: Path, case_id: str) -> Path:
    row = resolve_case(raw, case_id)
    task = {
        "schema_version": "widesearch.task.v1",
        "case_id": case_id,
        "evaluation": json.loads(row["evaluation"]),
    }
    case_dir = cases_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "task.json").write_text(
        json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (case_dir / "instruction.md").write_text(row["query"], encoding="utf-8")
    gold = gold_dir / f"{case_id}.csv"
    if not gold.is_file():
        raise FileNotFoundError(f"gold csv missing: {gold}")
    return case_dir


def fresh_workspace(*, cases_root: Path, case_id: str, run_id: str) -> Path:
    """Create a clean, isolated run workspace (re-entrant safe)."""
    ws = cases_root / case_id / "runs" / run_id
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)
    src = cases_root / case_id
    shutil.copy2(src / "task.json", ws / "task.json")
    shutil.copy2(src / "instruction.md", ws / "instruction.md")
    return ws


def stamp_run_start(ws: Path) -> float:
    started = time.time()
    (ws / ".run_started_at").write_text(str(started), encoding="utf-8")
    return started


def answer_is_fresh(ws: Path, started_at: float) -> tuple[bool, str]:
    answer = ws / "final_answer.md"
    if not answer.is_file():
        return False, "final_answer.md missing"
    if answer.stat().st_size == 0:
        return False, "final_answer.md empty"
    if answer.stat().st_mtime < started_at - 5:
        return False, "final_answer.md predates run start (stale answer)"
    return True, "ok"
