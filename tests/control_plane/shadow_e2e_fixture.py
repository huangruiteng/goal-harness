"""Disposable public CLI fixtures and scheduling-only process crash seams."""

from __future__ import annotations

import json
from pathlib import Path
import select
import subprocess
import sys
from dataclasses import dataclass

REPO = Path(__file__).resolve().parents[2]


@dataclass
class ShadowWorkspace:
    registry: Path
    runtime: Path
    state: Path
    goal: str = "goal-e2e"

    def arguments(self, *args: str) -> list[str]:
        return [
            "--registry",
            str(self.registry),
            "--runtime-root",
            str(self.runtime),
            "--format",
            "json",
            *args,
            "--goal-id",
            self.goal,
        ]

    def cli(self, *args: str, success: bool = True) -> dict:
        result = subprocess.run(
            [sys.executable, "-m", "loopx.cli", *self.arguments(*args)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if success:
            assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "Traceback" not in result.stderr, result.stderr
        return json.loads(result.stdout)

    def add(self, text: str) -> dict:
        return self.cli("todo", "add", "--role", "agent", "--text", text)

    def drain(self, **limits: str) -> dict:
        args = [
            item
            for key, value in limits.items()
            for item in ("--" + key.replace("_", "-"), value)
        ]
        return self.cli("authority-shadow", "drain", *args, success=False)

    def crash(self, window: str, *args: str) -> dict:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                CRASH_WORKER,
                window,
                str(self.state),
                *self.arguments(*args),
            ],
            cwd=REPO,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert child.stdout is not None
        try:
            readable, _, _ = select.select([child.stdout], [], [], 30)
            assert readable, "public CLI did not reach the requested persistence window"
            line = child.stdout.readline()
            if not line.startswith("BARRIER "):
                child.kill()
                stdout, stderr = child.communicate(timeout=10)
                raise AssertionError(f"No process barrier: {line}{stdout}\n{stderr}")
            payload = json.loads(line.removeprefix("BARRIER "))
            child.kill()
            child.communicate(timeout=10)
            assert child.returncode == -9
            return payload
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


def workspace(path: Path, *, bootstrap: bool = True) -> ShadowWorkspace:
    path.mkdir(parents=True, exist_ok=True)
    state = path / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "---\ngoal_id: goal-e2e\nhandoff_mode: hard_lease\n"
        "updated_at: 2026-09-01T00:00:00+00:00\n---\n\n## Agent Todo\n\n",
        encoding="utf-8",
    )
    runtime, registry = path / "runtime", path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": "goal-e2e",
                        "status": "active",
                        "repo": str(path),
                        "state_file": state.name,
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["agent-a", "agent-b"],
                            "runtime_shadow": {
                                "schema_version": "loopx_coordination_runtime_shadow_config_v0",
                                "enabled": True,
                                "provider": "file_v0",
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = ShadowWorkspace(registry, runtime, state)
    if bootstrap:
        boot = result.cli("coordination-shadow", "bootstrap", "--execute")["bootstrap"]
        assert boot["status"] == "applied", boot
    return result


CRASH_WORKER = r"""
import json, pathlib, sys, time
from loopx.cli import main
from loopx.control_plane.coordination import local_authority_shadow_adapter as adapter
from loopx.control_plane.coordination import local_authority_shadow_outbox as outbox
from loopx.control_plane.todos import active_state_editing
window, state = sys.argv[1], pathlib.Path(sys.argv[2])
def pause(payload=None):
    print('BARRIER ' + json.dumps(payload or {}), flush=True)
    time.sleep(40)
    raise RuntimeError('parent failed to terminate at persistence barrier')
actual_rpc = adapter.effect_runtime_result
def rpc(method, request, **kwargs):
    if method == 'coordination.runtime_shadow.commit_entry' and window == 'before_commit':
        pause({'request': request})
    result = actual_rpc(method, request, **kwargs)
    if method == 'coordination.runtime_shadow.commit_entry' and window == 'after_commit':
        pause({'request': request, 'result': result})
    return result
adapter.effect_runtime_result = rpc
actual_cursor = outbox.write_cursor
def cursor(*args, **kwargs):
    result = actual_cursor(*args, **kwargs)
    if window == 'after_cursor': pause()
    return result
outbox.write_cursor = cursor
actual_json = outbox.durable_write_json
def write_json(path, value):
    if window == 'before_marker' and path.name.endswith('.committed.json'): pause()
    return actual_json(path, value)
outbox.durable_write_json = write_json
actual_replace = active_state_editing.os.replace
def replace(source, target):
    is_primary = pathlib.Path(target) == state
    if is_primary and window == 'before_replace': pause()
    result = actual_replace(source, target)
    if is_primary and window == 'after_replace': pause()
    return result
active_state_editing.os.replace = replace
actual_unlink = pathlib.Path.unlink
def unlink(path, *args, **kwargs):
    result = actual_unlink(path, *args, **kwargs)
    if window == 'between_unlinks' and path.name.endswith('.prepared.json'): pause()
    return result
pathlib.Path.unlink = unlink
raise SystemExit(main(sys.argv[3:]))
"""
