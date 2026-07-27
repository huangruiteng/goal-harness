from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .planner_worker import (
    DEFAULT_PLANNER_MODEL,
    DEFAULT_WORKER_MODEL,
    build_planner_prompt,
    build_worker_step_prompt,
    normalize_planner_worker_plan,
)
from .codex_goal_baseline import stable_text_digest


TRAEX_PLANNER_WORKER_PROBE_SCHEMA_VERSION = "traex_planner_worker_probe_v0"
DEFAULT_TRAEX_PLANNER_MODEL = "GPT-5.5"
DEFAULT_TRAEX_WORKER_MODEL = "GPT-5.4"


class TraexPlannerWorkerError(RuntimeError):
    """Raised when the TraeX planner-worker probe fails."""


def _assistant_text_and_usage(jsonl: str) -> tuple[str, dict[str, int]]:
    parts: list[str] = []
    usage: dict[str, int] = {}
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") == "turn.completed" and isinstance(item.get("usage"), dict):
            usage = {
                key: int(value)
                for key, value in item["usage"].items()
                if isinstance(value, int)
            }
        payload = item.get("item")
        if isinstance(payload, dict) and payload.get("type") == "agent_message":
            parts.append(str(payload.get("text") or ""))
    return "\n".join(parts).strip(), usage


def _compact_traex_turn(*, model: str, jsonl: str) -> dict[str, Any]:
    assistant_text, usage = _assistant_text_and_usage(jsonl)
    return {
        "model": model,
        "usage": usage,
        "assistant_message_present": bool(assistant_text),
        "assistant_message_chars": len(assistant_text),
        "assistant_message_sha256": stable_text_digest(assistant_text) if assistant_text else None,
        "raw_assistant_message_recorded": False,
    }


def _run_traex_exec(
    *,
    traex_bin: str,
    model: str,
    prompt: str,
    cwd: Path,
    timeout_seconds: float,
) -> tuple[str, str]:
    command = [
        traex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--disallowed-tool",
        "exec_command",
        "--disallowed-tool",
        "apply_patch",
        "--model",
        model,
        prompt,
    ]
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise TraexPlannerWorkerError(
            f"traex exec failed for model={model}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout, result.stderr


def run_traex_planner_worker_probe(
    *,
    objective: str,
    task_instruction: str,
    planner_output_plan: dict[str, Any],
    traex_bin: str = "traex",
    planner_model: str = DEFAULT_TRAEX_PLANNER_MODEL,
    worker_model: str = DEFAULT_TRAEX_WORKER_MODEL,
    cwd: Path | str = ".",
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Run a read-only TraeX planner turn followed by a worker step turn."""

    workdir = Path(cwd).resolve()
    plan = normalize_planner_worker_plan(planner_output_plan)
    planner_prompt = build_planner_prompt(
        objective=objective,
        task_instruction=task_instruction,
    )
    planner_jsonl, planner_stderr = _run_traex_exec(
        traex_bin=traex_bin,
        model=planner_model,
        prompt=planner_prompt,
        cwd=workdir,
        timeout_seconds=timeout_seconds,
    )
    first_step = plan["steps"][0]
    worker_prompt = build_worker_step_prompt(plan=plan, step=first_step)
    worker_jsonl, worker_stderr = _run_traex_exec(
        traex_bin=traex_bin,
        model=worker_model,
        prompt=worker_prompt,
        cwd=workdir,
        timeout_seconds=timeout_seconds,
    )
    planner_turn = _compact_traex_turn(model=planner_model, jsonl=planner_jsonl)
    worker_turn = _compact_traex_turn(model=worker_model, jsonl=worker_jsonl)
    planner_usage = planner_turn.get("usage") if isinstance(planner_turn.get("usage"), dict) else {}
    worker_usage = worker_turn.get("usage") if isinstance(worker_turn.get("usage"), dict) else {}
    usage_keys = {
        *planner_usage.keys(),
        *worker_usage.keys(),
    }
    total_usage = {
        key: int(planner_usage.get(key, 0)) + int(worker_usage.get(key, 0))
        for key in sorted(usage_keys)
    }
    return {
        "schema_version": TRAEX_PLANNER_WORKER_PROBE_SCHEMA_VERSION,
        "runtime": "traex",
        "mode": "planner_worker",
        "planner_model": planner_model,
        "worker_model": worker_model,
        "planner_turn": planner_turn,
        "worker_turn": worker_turn,
        "total_usage": total_usage,
        "plan": {
            "schema_version": plan["schema_version"],
            "plan_id": plan["plan_id"],
            "step_count": len(plan["steps"]),
            "first_step_id": first_step["step_id"],
        },
        "boundary": {
            "read_only_traex_exec": True,
            "raw_prompts_recorded": False,
            "raw_assistant_messages_recorded": False,
            "raw_stderr_recorded": False,
            "planner_stderr_present": bool(planner_stderr.strip()),
            "worker_stderr_present": bool(worker_stderr.strip()),
        },
    }


def build_synthetic_planner_worker_plan(*, objective: str) -> dict[str, Any]:
    return normalize_planner_worker_plan(
        {
            "plan_id": "traex-planner-worker-synthetic-plan",
            "objective": objective,
            "steps": [
                {
                    "step_id": "implement-contract",
                    "target_files": ["loopx/planner_worker.py"],
                    "action_kind": "edit",
                    "instruction": "Describe the focused implementation change and validation commands.",
                    "verification": "Run the focused planner-worker smoke tests.",
                }
            ],
        }
    )


__all__ = [
    "DEFAULT_TRAEX_PLANNER_MODEL",
    "DEFAULT_TRAEX_WORKER_MODEL",
    "TRAEX_PLANNER_WORKER_PROBE_SCHEMA_VERSION",
    "TraexPlannerWorkerError",
    "build_synthetic_planner_worker_plan",
    "run_traex_planner_worker_probe",
]
