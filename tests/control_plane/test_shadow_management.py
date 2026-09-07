"""The local primary guard never creates state or bypasses a durable hold."""

import json
import hashlib
from pathlib import Path
import subprocess

import pytest

from loopx.control_plane.coordination.shadow_management import (
    ShadowManagementError,
    read_shadow_management_state,
    require_shadow_primary_write_allowed,
    shadow_management_state_path,
    shadow_maintenance_lock_target,
)


def test_absent_management_preserves_default_without_creating_files(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    assert require_shadow_primary_write_allowed(root, "goal-a") is None
    assert read_shadow_management_state(root, "goal-a") is None
    assert not root.exists()
    assert "authority-transition" in shadow_maintenance_lock_target(root, "goal-a").parts


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"status":"active"}'])
def test_corrupt_management_holds_before_any_primary_write(tmp_path: Path, raw: str) -> None:
    path = shadow_management_state_path(tmp_path, "goal-a")
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    before = path.read_bytes()
    with pytest.raises(ShadowManagementError) as failure:
        require_shadow_primary_write_allowed(tmp_path, "goal-a")
    assert failure.value.code == "shadow_management_state_invalid"
    assert path.read_bytes() == before


def test_python_reads_typescript_binding_and_rejects_cross_root_replay(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    script = """
import {bootstrapManagedShadow} from './loopx/control_plane/coordination/shadow_management.ts';
const root = process.argv[1];
const request = {runtime_root:root,goal_id:'goal-a',operation_id:'bootstrap:guard',source_version:'v1',source_snapshot:{},projection:{goal_id:'goal-a',todos:[],leases:[]}};
const result = await bootstrapManagedShadow(request,{withPrimaryLocks:async fn=>await fn(),verifySourceSnapshot:async()=>{}});
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "--input-type=module", "-e", script, str(root)],
        check=True, capture_output=True, text=True,
    )
    applied = json.loads(result.stdout)
    assert applied["status"] == "applied"
    binding = require_shadow_primary_write_allowed(root, "goal-a")
    assert binding is not None
    assert binding["capture_lineage_id"] == applied["capture_lineage_id"]
    other = tmp_path / "other-root"
    destination = shadow_management_state_path(other, "goal-a")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(shadow_management_state_path(root, "goal-a").read_bytes())
    with pytest.raises(ShadowManagementError, match="shadow_management_state_invalid"):
        require_shadow_primary_write_allowed(other, "goal-a")


@pytest.mark.parametrize("status", ["bootstrapping", "rolling_back"])
def test_pending_journal_is_a_primary_hold(tmp_path: Path, status: str) -> None:
    root_digest = "sha256:" + hashlib.sha256(str(tmp_path).encode()).hexdigest()
    state = {
        "schema_version": "loopx_shadow_management_state_v1", "goal_id": "goal-a",
        "source_root_digest": root_digest, "status": status, "binding": None,
        "operation": {"kind": "bootstrap" if status == "bootstrapping" else "rollback",
                      "operation_id": "operation:pending", "request_digest": "sha256:" + "1" * 64,
                      "manifest_digest": "sha256:" + "2" * 64, "phase": "prepared"},
        "previous_operation_id": None, "result": None,
    }
    path = shadow_management_state_path(tmp_path, "goal-a")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state))
    with pytest.raises(ShadowManagementError) as failure:
        require_shadow_primary_write_allowed(tmp_path, "goal-a")
    assert failure.value.code == "shadow_management_in_progress"


@pytest.mark.stage2c_e2e
def test_bound_source_path_comes_from_the_verified_typescript_bootstrap(tmp_path: Path) -> None:
    from loopx.control_plane.coordination import shadow_management as management
    from shadow_e2e_fixture import workspace

    w = workspace(tmp_path)
    binding = require_shadow_primary_write_allowed(w.runtime, w.goal)
    assert binding is not None
    before = {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()}
    assert management.read_shadow_bootstrap_source_path(w.runtime, w.goal, binding) == w.state
    with pytest.raises(ShadowManagementError, match="stale_generation"):
        management.read_shadow_bootstrap_source_path(w.runtime, w.goal, {**binding, "capture_lineage_id": "another-lineage"})
    assert {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()} == before


@pytest.mark.stage2c_e2e
@pytest.mark.parametrize("damage", ["altered", "missing"])
def test_bound_source_path_never_accepts_or_repairs_a_damaged_manifest(tmp_path: Path, damage: str) -> None:
    from loopx.control_plane.coordination import shadow_management as management
    from shadow_e2e_fixture import workspace

    w = workspace(tmp_path)
    binding = require_shadow_primary_write_allowed(w.runtime, w.goal)
    assert binding is not None
    [manifest] = management.shadow_management_directory(w.runtime, w.goal).glob("operations/*/manifest.json")
    if damage == "altered":
        value = json.loads(manifest.read_bytes())
        value["request"]["source_snapshot"]["state_path"] = str(tmp_path / "foreign-state.md")
        manifest.write_text(json.dumps(value))
    else:
        manifest.unlink()
    before = {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()}
    with pytest.raises(ShadowManagementError, match="shadow_management_manifest_invalid"):
        management.read_shadow_bootstrap_source_path(w.runtime, w.goal, binding)
    assert {str(path.relative_to(w.runtime)): path.read_bytes() for path in w.runtime.rglob("*") if path.is_file()} == before
