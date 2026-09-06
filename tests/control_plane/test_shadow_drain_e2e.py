"""Receipt, cursor and crash invariants through real CLI and independent TS processes."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from shadow_e2e_fixture import REPO, ShadowWorkspace, workspace
from loopx.control_plane.coordination import local_authority_shadow_adapter as adapter
from loopx.control_plane.coordination import local_authority_shadow_outbox as outbox


pytestmark = pytest.mark.stage2c_e2e


def directory(w: ShadowWorkspace) -> Path:
    return outbox.partition_directory(w.runtime, w.goal, "todos")


def history(w: ShadowWorkspace) -> dict:
    return adapter.read_local_authority_shadow(
        runtime_root=w.runtime, goal_id=w.goal, scan_limit=10_000
    )


def pending(w: ShadowWorkspace, text: str = "One primary mutation") -> dict:
    return w.crash("before_commit", "todo", "add", "--role", "agent", "--text", text)


def snapshot(path: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


def test_public_primary_maps_one_to_one_to_receipts_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    w = workspace(tmp_path)
    ids = [w.add(f"Public fact {index}")["todo_id"] for index in range(3)]
    w.drain()
    view = history(w)
    transactions = view["proof"]["transactions"]
    assert len(transactions) == 4  # One complete baseline, three actual mutations.
    assert [item["todo_id"] for item in view["head"]["todos"]] == sorted(ids)
    assert view["head"]["handoff_mode"] == "hard_lease"
    assert view["head"]["leases"] == []
    assert [tx["receipts"][0]["seq"] for tx in transactions[1:]] == [1, 2, 3]
    assert all(tx["receipts"][0]["no_op"] is False for tx in transactions[1:])
    assert w.drain()["outcome"] == "nothing_pending"
    assert history(w)["proof"]["transactions"] == transactions
    assert [p.name for p in directory(w).iterdir()] == ["drain-cursor.json"]
    for args in (("qualify",), ("read-candidate", "--todo-id", ids[0])):
        arguments = w.arguments("coordination-shadow", *args)
        arguments[arguments.index("--format") + 1] = "markdown"
        result = subprocess.run([sys.executable, "-m", "loopx.cli", *arguments],
                                cwd=REPO, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "qualification_scope: `bounded`" in result.stdout
        assert "sustained_parity_verdict: `not_evaluated`" in result.stdout
        assert "minimum_primary_mutations: `3`" in result.stdout


def test_public_mutation_has_no_second_snapshot_mirror(tmp_path: Path) -> None:
    w = workspace(tmp_path)
    assert w.add("Exactly one durable primary mutation")["added"] is True
    module = REPO / "loopx/control_plane/coordination/file_authority_store.ts"
    script = (
        f"import {{FileAuthorityStore}} from {json.dumps(module.as_uri())};"
        "const store=new FileAuthorityStore(process.argv[1],process.argv[2],{existingOnly:true});"
        "process.stdout.write(JSON.stringify(await store.scanCommitted(null,10000)));"
    )
    readback = subprocess.run(
        ["node", "--no-warnings", "--experimental-strip-types", "--input-type=module", "-e", script,
         str(w.runtime / "authority-shadow/file-v0"), w.goal],
        capture_output=True, text=True, check=True, timeout=30,
    )
    page = json.loads(readback.stdout)
    assert page["status"] == "page", page
    assert len(page["transactions"]) == 2, page  # Full baseline plus one mutation.
    assert page["transactions"][0]["receipts"] == []
    assert len(page["transactions"][1]["receipts"]) == 1
    assert page["transactions"][1]["receipts"][0]["write_class"] == "todo_add"


@pytest.mark.parametrize(
    "attack",
    [
        "high_water",
        "fake_digest",
        "string_seq",
        "boolean_seq",
        "missing_anchor",
        "wrong_root",
        "wrong_lineage",
    ],
)
def test_cursor_cannot_authorize_deletion_or_hide_mutations(
    tmp_path: Path, attack: str
) -> None:
    w = workspace(tmp_path)
    w.add("First captured mutation")
    pending(w, "Second real mutation")
    d = directory(w)
    cursor_path = d / "drain-cursor.json"
    value = json.loads(cursor_path.read_bytes())
    if attack == "high_water":
        value["last_seq"] = 9_999_999_999
    elif attack == "fake_digest":
        value["last_partition_digest"] = "sha256:" + "f" * 64
    elif attack == "string_seq":
        value["last_seq"] = "1"
    elif attack == "boolean_seq":
        value["last_seq"] = True
    elif attack == "missing_anchor":
        value["last_cursor"] = "uncommitted-cursor"
    else:
        entry = next(d.glob("*.prepared.json"))
        record = json.loads(entry.read_bytes())
        record[
            "source_root_digest" if attack == "wrong_root" else "capture_lineage_id"
        ] = "sha256:" + "a" * 64 if attack == "wrong_root" else "other-lineage"
        entry.write_text(json.dumps(record))
    cursor_path.write_text(json.dumps(value))
    before = snapshot(d)
    result = w.drain()
    assert result["ok"] is False, result
    assert result["reason_code"] in {
        "outbox_cursor_invalid",
        "outbox_cursor_unproved",
        "outbox_file_invalid",
        "stale_generation",
    }
    assert snapshot(d) == before
    assert len(history(w)["proof"]["transactions"]) == 2
    status = w.cli("authority-shadow", "status", success=False)
    assert "outbox" in status


@pytest.mark.parametrize("window", ["after_commit", "after_cursor", "between_unlinks"])
def test_real_sigkill_drain_windows_recover_from_exact_receipts(
    tmp_path: Path, window: str
) -> None:
    w = workspace(tmp_path)
    w.crash(
        window,
        "todo",
        "add",
        "--role",
        "agent",
        "--text",
        "Committed before process death",
    )
    before = history(w)["proof"]["transactions"]
    assert len(before) == 2
    result = w.drain()
    assert result["ok"] is True, result
    assert result["replayed"] == 1
    assert result["delivered"] == 0
    assert history(w)["proof"]["transactions"] == before
    assert outbox.read_cursor(directory(w))["last_seq"] == 1
    assert [p.name for p in directory(w).iterdir()] == ["drain-cursor.json"]


def test_missing_cursor_recovers_only_from_complete_verified_history(
    tmp_path: Path,
) -> None:
    w = workspace(tmp_path)
    w.add("First")
    w.add("Second")
    before = history(w)["proof"]["transactions"]
    (directory(w) / "drain-cursor.json").unlink()
    assert w.drain()["ok"] is True
    assert outbox.read_cursor(directory(w))["last_seq"] == 2
    w.add("Third")
    assert history(w)["proof"]["transactions"][:3] == before
    assert outbox.read_cursor(directory(w))["last_seq"] == 3


@pytest.mark.parametrize("window", ["before_replace", "after_replace", "before_marker"])
def test_primary_sigkill_preserves_complete_bytes_and_proves_before_marker(
    tmp_path: Path, window: str
) -> None:
    w = workspace(tmp_path)
    old = w.state.read_bytes()
    w.crash(
        window, "todo", "add", "--role", "agent", "--text", "Atomic primary sentence"
    )
    current = w.state.read_bytes()
    listed = w.cli("todo", "list")["todos"]
    assert (current == old) is (window == "before_replace")
    assert len(listed) == (0 if window == "before_replace" else 1)
    assert not list(directory(w).glob("*.committed.json"))
    result = w.drain()
    assert result["ok"] is True, result
    receipt = history(w)["proof"]["transactions"][-1]["receipts"][0]
    assert receipt["resolution"] == (
        "abandoned" if window == "before_replace" else "committed_proven_by_readback"
    )
    assert receipt["no_op"] is (window == "before_replace")


def test_prepared_a_b_a_never_infers_first_write_was_abandoned(tmp_path: Path) -> None:
    w = workspace(tmp_path)
    w.crash("before_marker", "handoff-mode", "set", "--mode", "soft_claim")
    # A later real writer returns the canonical primary to its initial A.
    w.cli("handoff-mode", "set", "--mode", "hard_lease")
    assert w.cli("handoff-mode", "show")["handoff_mode"] == "hard_lease"
    before = snapshot(directory(w))
    result = w.drain()
    assert (
        result["ok"] is False and result["reason_code"] == "outbox_source_unproved"
    ), result
    assert snapshot(directory(w)) == before
    assert len(history(w)["proof"]["transactions"]) == 1
    qualify = w.cli("coordination-shadow", "qualify", success=False)
    assert qualify["ok"] is False


def test_concurrent_real_drainers_commit_once_without_cursor_regression(
    tmp_path: Path,
) -> None:
    w = workspace(tmp_path)
    for index in range(3):
        pending(w, f"Concurrent {index}")
    argv = [
        sys.executable,
        "-m",
        "loopx.cli",
        *w.arguments("authority-shadow", "drain", "--lock-timeout-seconds", "2"),
    ]
    children = [
        subprocess.Popen(
            argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    for child in children:
        stdout, stderr = child.communicate(timeout=45)
        assert "Traceback" not in stderr
        result = json.loads(stdout)
        assert result["outcome"] in {"drained", "nothing_pending", "drain_deferred"}, (
            result
        )
    assert w.drain()["ok"] is True
    txs = history(w)["proof"]["transactions"]
    assert len(txs) == 4
    assert len({tx["operation_id"] for tx in txs}) == 4
    assert outbox.read_cursor(directory(w))["last_seq"] == 3


def test_bounded_drain_preserves_unprocessed_entries(tmp_path: Path) -> None:
    w = workspace(tmp_path)
    for index in range(3):
        pending(w, f"Bounded {index}")
    result = w.drain(max_entries="1")
    assert result["ok"] and result["delivered"] == 1 and result["budget_exhausted"], (
        result
    )
    assert [entry.seq for entry in outbox.list_entries(directory(w))] == [2, 3]
    assert w.drain()["ok"]
    assert len(history(w)["proof"]["transactions"]) == 4
