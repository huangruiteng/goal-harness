"""Canonical Todo updates share the durable management boundary.

The CLI and native adapter use real file providers. Scheduling seams only pause
real commits or management effects; they never replace their results. Pending
journals are produced by the management primitive, independently of promotion:
these tests do not claim that shadow bootstrap can promote a canonical provider.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import select
import subprocess
import sys

import pytest

from canonical_authority_fixture import initialize_canonical_authority
from loopx.control_plane.coordination.coordination_state_contract import (
    TODO_DOMAIN_ITEM_SCHEMA_VERSION,
    TODO_DOMAIN_READ_RECORD_SCHEMA_VERSION,
    TODO_DOMAIN_RECORD_FIELDS,
)
from loopx.control_plane.coordination.local_authority_shadow_projection import canonical_bytes
from loopx.control_plane.coordination.runtime_shadow import build_todo_runtime_shadow_projection
from loopx.control_plane.coordination.shadow_management import (
    read_shadow_management_state,
    shadow_management_state_path,
)
from loopx.control_plane.effect_runtime import effect_runtime_result

REPO = Path(__file__).resolve().parents[2]
GOAL, TODO = "goal-update", "todo_update_probe"
pytestmark = pytest.mark.stage2c_e2e


@dataclass
class Workspace:
    runtime: Path
    registry: Path
    state: Path
    projection: dict

    def command(self, text: str = "Updated through the public CLI") -> list[str]:
        return [sys.executable, "-m", "loopx.cli", "--format", "json",
                "--registry", str(self.registry), "--runtime-root", str(self.runtime),
                "todo", "update", "--goal-id", GOAL, "--todo-id", TODO,
                "--agent-id", "agent-a", "--text", text]

    def request(self, **changes: object) -> dict:
        return {"schema_version": "loopx_local_coordination_todo_update_request_v0",
                "runtime_root": str(self.runtime), "goal_id": GOAL, "todo_id": TODO,
                "role": "agent", "actor_agent_id": "agent-a", "registered_agents": ["agent-a", "agent-b"],
                "operation_id": "native-update-operation", "patch": {"text": "Updated through native RPC"},
                "clear_fields": [], "dry_run": False, "observed_at": "2026-09-06T06:00:00Z", **changes}


@pytest.fixture(params=["native", "compat_v0"])
def workspace(tmp_path: Path, request: pytest.FixtureRequest) -> Workspace:
    runtime = tmp_path / "runtime"
    state = tmp_path / "ACTIVE_GOAL_STATE.md"
    state.write_text("# Canonical display is not a transaction input.\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": 1, "common_runtime_root": str(runtime),
        "goals": [{"id": GOAL, "repo": str(tmp_path), "state_file": state.name,
                   "coordination": {"registered_agents": ["agent-a", "agent-b"]}}]}), encoding="utf-8")
    todo = {"schema_version": TODO_DOMAIN_ITEM_SCHEMA_VERSION, "todo_id": TODO,
            "text": "Original provider text", "role": "agent", "status": "open", "done": False,
            "archive_state": "active", "claimed_by": "agent-a", "note": "Keep the note",
            "required_capabilities": ["code_review"], "excluded_agents": ["agent-b"],
            "evidence": "Complete provider metadata"}
    if request.param == "native":
        projection = {"goal_id": GOAL, "handoff_mode": "soft_claim", "todos": [todo], "leases": [],
            "todo_read_model": {"schema_version": TODO_DOMAIN_READ_RECORD_SCHEMA_VERSION, "todo_count": 1,
                "records_sha256": hashlib.sha256(canonical_bytes([todo])).hexdigest(),
                "contract_fields": list(TODO_DOMAIN_RECORD_FIELDS)}}
    else:
        todo.update(schema_version="todo_item_v0", index=7, source_section="Agent Todo")
        projection = build_todo_runtime_shadow_projection(goal_id=GOAL, todos=[todo], handoff_mode="soft_claim")
    initialize_canonical_authority(runtime, GOAL, projection, state_path=state)
    state.unlink()  # Neither update route may require or recreate Markdown.
    return Workspace(runtime, registry, state, projection)


NODE = r"""
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {once} from 'node:events';
import {join} from 'node:path';
const input = JSON.parse(process.argv[1]);
const base = new URL(input.module_base);
const {FileAuthorityStore} = await import(new URL('file_authority_store.ts', base));
const {updateLocalCoordinationTodo} = await import(new URL('local_authority_runtime.ts', base));
const management = await import(new URL('shadow_management.ts', base));
const store = new FileAuthorityStore(join(input.request.runtime_root, 'authority', 'file-v0'), input.request.goal_id, {existingOnly:true});
const barrier = async (phase) => {process.stdout.write('BARRIER ' + phase + '\n'); await once(process.stdin, 'data');};
if (input.mode.endsWith('_wait')) {
  const actualOpen = fs.promises.open;
  let notified = false;
  const lock = management.shadowMaintenanceLockPath(input.request.runtime_root, input.request.goal_id) + '.ts-effect.lock';
  fs.promises.open = async (path, flags, ...args) => {
    if (String(path) === lock && flags === 'wx' && !notified) {
      notified = true; process.stdout.write('BARRIER lock-attempt\n');
    }
    return await actualOpen(path, flags, ...args);
  };
  syncBuiltinESMExports();
}
let result;
if (input.mode === 'inspect') {
  result = {head:await store.loadAuthority(), receipt:input.operation_id ? await store.readReceipt(input.operation_id) : null,
    document_path:store.path};
} else if (input.mode.startsWith('update')) {
  if (input.mode === 'update_paused') {
    const actualCommit = store.commitAuthority.bind(store);
    store.commitAuthority = async (commit) => {await barrier('commit'); return await actualCommit(commit);};
  }
  result = await updateLocalCoordinationTodo(input.request, {createStore:() => store});
} else {
  const dependencies = {withPrimaryLocks:async (fn) => await fn(), verifySourceSnapshot:async () => {},
    afterEffect:async (phase) => {if (phase === input.stop_at) await barrier(phase);}};
  result = input.mode.startsWith('bootstrap') ? await management.bootstrapManagedShadow(input.request, dependencies)
    : await management.rollbackManagedShadow(input.request, dependencies);
}
process.stdout.write(JSON.stringify(result) + '\n');
"""


def node_command(mode: str, request: dict, **options: object) -> list[str]:
    base = (REPO / "loopx/control_plane/coordination").as_uri() + "/"
    return ["node", "--no-warnings", "--experimental-strip-types", "--input-type=module", "-e", NODE,
            json.dumps({"mode": mode, "request": request, "module_base": base, **options})]


def inspect(workspace: Workspace, operation_id: str | None = None) -> dict:
    result = subprocess.run(node_command("inspect", workspace.request(), operation_id=operation_id),
        cwd=REPO, capture_output=True, text=True, check=True, timeout=20)
    value = json.loads(result.stdout)
    assert value["head"]["status"] == "loaded", value
    return value


def invoke(workspace: Workspace, transport: str, **changes: object) -> dict:
    if transport == "rpc":
        return effect_runtime_result("coordination.local_authority.todo_update", workspace.request(**changes))
    args = workspace.command()
    if changes.get("dry_run"):
        args.append("--dry-run")
    result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=20)
    assert "Traceback" not in result.stderr, result.stderr
    return json.loads(result.stdout)


def bootstrap_request(workspace: Workspace) -> dict:
    return {"runtime_root": str(workspace.runtime), "goal_id": GOAL, "operation_id": "maintenance-bootstrap",
            "source_version": "fixture-source", "source_snapshot": {"state_path": str(workspace.state)},
            "projection": workspace.projection}


def start(command: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(command, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def expect_barrier(child: subprocess.Popen[str], phase: str) -> None:
    assert child.stdout is not None
    ready, _, _ = select.select([child.stdout], [], [], 10)
    assert ready, "real process did not reach the scheduling boundary"
    line = child.stdout.readline().strip()
    assert line == "BARRIER " + phase, line


def stop(child: subprocess.Popen[str]) -> None:
    if child.poll() is None:
        child.kill()
    child.communicate(timeout=10)


def pending(workspace: Workspace, kind: str) -> subprocess.Popen[str]:
    request = bootstrap_request(workspace)
    if kind == "rolling_back":
        applied = subprocess.run(node_command("bootstrap", request), cwd=REPO,
            capture_output=True, text=True, check=True, timeout=20)
        seed = json.loads(applied.stdout)
        assert seed["status"] == "applied", seed
        request = {"runtime_root": str(workspace.runtime), "goal_id": GOAL, "operation_id": "maintenance-rollback",
                   "expected_provider_revision": seed["provider_revision"]}
    mode = "rollback" if kind == "rolling_back" else "bootstrap"
    phase = mode + "_prepared"
    child = start(node_command(mode, request, stop_at=phase))
    try:
        expect_barrier(child, phase)
        assert read_shadow_management_state(workspace.runtime, GOAL)["status"] == kind
        return child
    except BaseException:
        stop(child)
        raise


@pytest.mark.parametrize("transport", ["cli", "rpc"])
def test_native_update_preserves_complete_records_and_exact_receipts(workspace: Workspace, transport: str) -> None:
    before = inspect(workspace)
    preview = invoke(workspace, transport, dry_run=True)
    assert preview["status"] == "planned", preview
    assert inspect(workspace)["head"] == before["head"]
    result = invoke(workspace, transport)
    assert result["status"] == "applied", result
    receipt = result["original_receipt"]
    after = inspect(workspace, receipt["operation_id"])
    assert after["receipt"]["status"] == "found"
    assert after["receipt"]["receipts"] == [receipt]
    assert after["receipt"]["provider_revision"] == result["provider_revision"] == after["head"]["provider_revision"]
    original = before["head"]["head"]["todos"][0]
    updated = after["head"]["head"]["todos"][0]
    assert updated == {**original, "text": "Updated through the public CLI" if transport == "cli" else "Updated through native RPC",
                       "last_actor_agent_id": "agent-a", "updated_at": updated["updated_at"]}
    assert after["head"]["head"]["todo_read_model"]["schema_version"] == before["head"]["head"]["todo_read_model"]["schema_version"]
    assert after["head"]["head"]["leases"] == []
    assert result["legacy_fallback_used"] is False
    assert not workspace.state.exists()
    assert not (workspace.runtime / "authority-shadow").exists()
    if transport == "rpc":
        replay = invoke(workspace, transport)
        assert replay["status"] == "replayed"
        assert replay["original_receipt"] == receipt
        assert inspect(workspace)["head"] == after["head"]


@pytest.mark.parametrize("transport", ["cli", "rpc"])
@pytest.mark.parametrize("management", ["corrupt", "bootstrapping", "rolling_back"])
def test_native_update_holds_before_primary_for_management(workspace: Workspace, transport: str, management: str) -> None:
    if management == "corrupt":
        path = shadow_management_state_path(workspace.runtime, GOAL)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{corrupt", encoding="utf-8")
    else:
        child = pending(workspace, management)
        stop(child)  # The actual durable intent survives a real SIGKILL.
        assert child.returncode == -9
    before = inspect(workspace)
    document = Path(before["document_path"])
    original_bytes = document.read_bytes()
    management_path = shadow_management_state_path(workspace.runtime, GOAL)
    management_bytes = management_path.read_bytes()
    result = invoke(workspace, transport)
    expected = "shadow_management_state_invalid" if management == "corrupt" else "shadow_management_in_progress"
    assert result.get("error_code", result.get("reason_code")) == expected, result
    assert document.read_bytes() == original_bytes
    assert management_path.read_bytes() == management_bytes
    assert inspect(workspace, "native-update-operation")["receipt"]["status"] == "missing"
    assert not workspace.state.exists()


def test_native_update_waits_for_management_then_rechecks_intent(workspace: Workspace) -> None:
    manager = pending(workspace, "bootstrapping")
    writer = start(node_command("update_wait", workspace.request()))
    try:
        expect_barrier(writer, "lock-attempt")
        before = inspect(workspace)
        assert writer.poll() is None
        stop(manager)
        output, error = writer.communicate(timeout=20)
        assert writer.returncode == 0, output + error
        result = json.loads(output)
        assert result["reason_code"] == "shadow_management_in_progress", result
        assert inspect(workspace)["head"] == before["head"]
    finally:
        stop(writer)
        stop(manager)


def test_native_update_retains_maintenance_lock_through_actual_commit(workspace: Workspace) -> None:
    writer = start(node_command("update_paused", workspace.request()))
    manager = None
    try:
        expect_barrier(writer, "commit")
        before = inspect(workspace)
        manager = start(node_command("bootstrap_wait", bootstrap_request(workspace), stop_at="bootstrap_prepared"))
        expect_barrier(manager, "lock-attempt")
        # An actual manager attempts M while the provider commit is paused.
        ready, _, _ = select.select([manager.stdout], [], [], .2)
        assert not ready, "management published an intent before the native commit released M"
        assert read_shadow_management_state(workspace.runtime, GOAL) is None
        output, error = writer.communicate("continue\n", timeout=20)
        assert writer.returncode == 0, output + error
        result = json.loads(output)
        assert result["status"] == "applied", result
        expect_barrier(manager, "bootstrap_prepared")
        after = inspect(workspace, result["original_receipt"]["operation_id"])
        assert after["receipt"]["status"] == "found"
        assert after["head"]["provider_revision"] != before["head"]["provider_revision"]
        assert read_shadow_management_state(workspace.runtime, GOAL)["status"] == "bootstrapping"
    finally:
        stop(writer)
        if manager is not None:
            stop(manager)
