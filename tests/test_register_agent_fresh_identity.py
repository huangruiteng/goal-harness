from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loopx.cli_commands import registry_admin

GOAL_ID = "fresh-agent-race-fixture"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _goal(project: Path, source_registry: Path, agents: list[str]) -> dict[str, object]:
    return {
        "id": GOAL_ID,
        "domain": "fresh-agent-race",
        "status": "active",
        "repo": str(project),
        "state_file": f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md",
        "adapter": {"kind": "fixture", "status": "connected-read-only"},
        "coordination": {
            "write_scope": [],
            "claim_ttl_minutes": 30,
            "requires_parent_approval": ["write", "publish", "production-action"],
            "registered_agents": agents,
            "agent_model": "peer_v1",
        },
        "source_registry": str(source_registry),
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_root = tmp_path / "runtime"
    project = tmp_path / "project"
    source_registry = project / ".loopx" / "registry.json"
    state_file = project / f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("# Active Goal State\n\n## Agent Todo\n\n", encoding="utf-8")
    project_payload = {
        "schema_version": "0.1",
        "common_runtime_root": str(runtime_root),
        "goals": [_goal(project, source_registry, ["codex-existing"])],
    }
    _write_json(source_registry, project_payload)
    global_registry = runtime_root / "registry.global.json"
    _write_json(
        global_registry,
        {
            **project_payload,
            "registry_role": "global-local",
        },
    )
    return runtime_root, source_registry, global_registry


def test_require_new_registration_is_atomic_under_concurrency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)
    barrier = threading.Barrier(2)

    def coordinated_probe(path: Path, *, create_parent: bool) -> dict[str, object]:
        assert create_parent is True
        if path == global_registry:
            barrier.wait(timeout=5)
        return {"ok": True, "path": str(path)}

    monkeypatch.setattr(registry_admin, "probe_registry_write_path", coordinated_probe)

    def register() -> dict[str, object]:
        return registry_admin.register_agent_via_source_registry(
            runtime_root_arg=str(runtime_root),
            goal_id=GOAL_ID,
            agent_ids=["codex-fresh"],
            require_new=True,
            execute=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: register(), range(2)))

    successes = [result for result in results if result.get("ok") is True]
    collisions = [
        result
        for result in results
        if result.get("error_kind") == "agent_identity_already_registered"
    ]
    assert len(successes) == 1, results
    assert successes[0]["changed"] is True
    assert successes[0]["written"] is True
    assert successes[0]["registration_readback"]["verified"] is True
    assert len(collisions) == 1, results
    assert collisions[0]["changed"] is False
    assert collisions[0]["written"] is False

    source_goal = json.loads(source_registry.read_text(encoding="utf-8"))["goals"][0]
    assert source_goal["coordination"]["registered_agents"] == [
        "codex-existing",
        "codex-fresh",
    ]
