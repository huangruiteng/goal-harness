from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GOAL_ID = "settlement-cli-fixture"
AGENT_ID = "codex-settlement-cli"
TODO_ID = "todo_fixture_settlement"
TURN_ID = "turn-settlement-cli-1"


def _write_fixture(
    root: Path,
    *,
    required_capability: str | None = None,
) -> tuple[Path, Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    state_file = f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    state_path = project / state_file
    registry_path = project / ".loopx" / "registry.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    capability_metadata = (
        f" required_capabilities={required_capability}"
        if required_capability
        else ""
    )
    state_path.write_text(
        "---\n"
        "status: active-read-only\n"
        "owner_mode: goal\n"
        'objective: "Settle one standard Codex App delivery."\n'
        "updated_at: 2026-01-01T00:00:00+00:00\n"
        "---\n\n"
        "# Settlement CLI Fixture\n\n"
        "## Objective\n\n"
        "Settle one standard Codex App delivery.\n\n"
        "## Next Action\n\n"
        "- Validate and settle the selected delivery.\n\n"
        "## Agent Todo\n\n"
        "- [ ] [P1] Validate and settle the selected delivery.\n"
        f"  <!-- loopx:todo todo_id={TODO_ID} status=open "
        "task_class=advancement_task action_kind=validate"
        f"{capability_metadata} -->\n",
        encoding="utf-8",
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "settlement-cli-fixture",
                        "status": "active-read-only",
                        "repo": str(project),
                        "state_file": state_file,
                        "adapter": {
                            "kind": "read_only_project_map_v0",
                            "status": "connected-read-only",
                        },
                        "coordination": {
                            "registered_agents": [AGENT_ID],
                            "agent_model": "peer_v1",
                        },
                        "authority_sources": [],
                        "quota": {
                            "compute": 1.0,
                            "window_hours": 24,
                            "allowed_slots": 2,
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return project, runtime, registry_path


def _run_cli(
    registry_path: Path,
    runtime: Path,
    *args: str,
) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime),
            "--format",
            "json",
            *args,
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, json.loads(result.stdout)


def _spend_run_count(runtime: Path) -> int:
    index_path = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"
    if not index_path.exists():
        return 0
    return sum(
        1
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("classification") == "quota_slot_spent"
    )


def _classification_count(runtime: Path, classification: str) -> int:
    index_path = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"
    if not index_path.exists():
        return 0
    return sum(
        1
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("classification") == classification
    )


def _heartbeat_receipt_count(runtime: Path, turn_instance_id: str) -> int:
    log_path = runtime / "goals" / GOAL_ID / "rollout-event-log.jsonl"
    if not log_path.exists():
        return 0
    return sum(
        1
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if (
            (event := json.loads(line)).get("event_kind") == "quota_should_run"
            and event.get("run_id") == turn_instance_id
            and event.get("agent_id") == AGENT_ID
        )
    )


def _configure_read_only_todo(project: Path) -> Path:
    state_path = project / f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    state_text = state_path.read_text(encoding="utf-8")
    state_path.write_text(
        state_text.replace(
            "action_kind=validate -->",
            "action_kind=validate "
            "continuation_policy=same_agent_non_delivery "
            "required_capabilities=shell%2Cfilesystem_read -->",
        ),
        encoding="utf-8",
    )
    return state_path


def _initialize_git_checkout(project: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/example/read-only-settlement-fixture.git",
        ],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )


def _strip_heartbeat_workspace_causality(runtime: Path) -> None:
    log_path = runtime / "goals" / GOAL_ID / "rollout-event-log.jsonl"
    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for event in events:
        if (
            event.get("event_kind") == "quota_should_run"
            and event.get("run_id") == TURN_ID
            and isinstance(event.get("details"), dict)
        ):
            event["details"].pop("delivery_workspace_causality", None)
            for key in tuple(event["details"]):
                if key.startswith("delivery_workspace_"):
                    event["details"].pop(key)
    log_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )


def test_standard_codex_app_settlement_is_receipted_and_idempotent(
    tmp_path: Path,
) -> None:
    project, runtime, registry_path = _write_fixture(tmp_path)
    binding = (
        "--agent-id",
        AGENT_ID,
        "--todo-id",
        TODO_ID,
        "--turn-instance-id",
        TURN_ID,
    )

    guard_rc, guard = _run_cli(
        registry_path,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--turn-instance-id",
        TURN_ID,
        "--scan-path",
        str(project),
    )

    assert guard_rc == 0, guard
    identity = guard["heartbeat_receipt"]["settlement_identity"]
    assert identity["todo_id"] == TODO_ID
    assert identity["effect_id"] == (f"{GOAL_ID}:{AGENT_ID}:{TODO_ID}:{TURN_ID}")

    complete_args = (
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--claimed-by",
        AGENT_ID,
        "--evidence",
        "original delivery validated",
        "--next-agent-todo",
        "Continue the explicit successor delivery.",
        "--next-claimed-by",
        AGENT_ID,
        "--next-action-kind",
        "implement",
    )
    complete_rc, complete = _run_cli(
        registry_path,
        runtime,
        *complete_args,
    )

    assert complete_rc == 0, complete
    assert complete["settlement_result"]["ok"] is True
    assert [
        receipt["step_kind"] for receipt in complete["settlement_result"]["receipts"]
    ] == ["validation"]
    successor_id = complete["next_todos"][0]["todo_id"]
    assert successor_id != TODO_ID
    complete_replay_rc, complete_replay = _run_cli(
        registry_path,
        runtime,
        *complete_args,
    )
    assert complete_replay_rc == 0, complete_replay
    assert complete_replay["idempotent_replay"] is True
    assert complete_replay["settlement_result"]["ok"] is True

    refresh_args = (
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        "--classification",
        "validated_progress",
        "--delivery-batch-scale",
        "single_surface",
        "--delivery-outcome",
        "outcome_progress",
        *binding,
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    refresh_rc, refresh = _run_cli(
        registry_path,
        runtime,
        *refresh_args,
    )

    assert refresh_rc == 0, refresh
    assert refresh["settlement_result"]["ok"] is True
    assert [
        receipt["step_kind"] for receipt in refresh["settlement_result"]["receipts"]
    ] == ["validation", "durable_writeback"]
    refresh_replay_rc, refresh_replay = _run_cli(
        registry_path,
        runtime,
        *refresh_args,
    )
    assert refresh_replay_rc == 0, refresh_replay
    assert refresh_replay["idempotent_replay"] is True
    assert _classification_count(runtime, "validated_progress") == 1

    fresh_guard_rc, fresh_guard = _run_cli(
        registry_path,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--scan-path",
        str(project),
    )
    assert fresh_guard_rc == 0, fresh_guard
    assert fresh_guard["selected_todo"]["todo_id"] == successor_id

    spend_args = (
        "quota",
        "spend-slot",
        "--goal-id",
        GOAL_ID,
        "--slots",
        "1",
        "--source",
        "heartbeat",
        "--execute",
        *binding,
        "--scan-path",
        str(project),
    )
    spend_rc, spend = _run_cli(registry_path, runtime, *spend_args)
    replay_rc, replay = _run_cli(registry_path, runtime, *spend_args)

    assert spend_rc == 0, spend
    assert spend["settlement_result"]["ok"] is True
    assert [
        receipt["step_kind"] for receipt in spend["settlement_result"]["receipts"]
    ] == ["validation", "durable_writeback", "quota_spend"]
    assert replay_rc == 0, replay
    assert replay["idempotent_replay"] is True
    assert replay["appended"] is False
    assert _spend_run_count(runtime) == 1


def test_same_turn_identityless_guard_upgrades_and_settles_full_chain(
    tmp_path: Path,
) -> None:
    project, runtime, registry_path = _write_fixture(
        tmp_path,
        required_capability="network",
    )
    binding = (
        "--agent-id",
        AGENT_ID,
        "--todo-id",
        TODO_ID,
        "--turn-instance-id",
        TURN_ID,
    )
    guard_args = (
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--turn-instance-id",
        TURN_ID,
        "--scan-path",
        str(project),
    )

    first_rc, first = _run_cli(registry_path, runtime, *guard_args)
    upgraded_rc, upgraded = _run_cli(
        registry_path,
        runtime,
        *guard_args,
        "--available-capability",
        "network",
    )
    replay_rc, replay = _run_cli(
        registry_path,
        runtime,
        *guard_args,
        "--available-capability",
        "network",
    )

    assert first_rc == 0, first
    assert "settlement_identity" not in first["heartbeat_receipt"]
    assert upgraded_rc == 0, upgraded
    assert upgraded["heartbeat_receipt"]["status"] == "upgraded"
    identity = upgraded["heartbeat_receipt"]["settlement_identity"]
    assert identity["todo_id"] == TODO_ID
    assert identity["effect_id"] == f"{GOAL_ID}:{AGENT_ID}:{TODO_ID}:{TURN_ID}"
    assert replay_rc == 0, replay
    assert replay["heartbeat_receipt"]["status"] == "replayed"
    assert replay["heartbeat_receipt"]["event_id"] == upgraded["heartbeat_receipt"]["event_id"]
    assert _heartbeat_receipt_count(runtime, TURN_ID) == 2

    complete_rc, complete = _run_cli(
        registry_path,
        runtime,
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--claimed-by",
        AGENT_ID,
        "--evidence",
        "identity upgrade delivery validated",
        "--next-agent-todo",
        "Continue after the identity upgrade delivery.",
        "--next-claimed-by",
        AGENT_ID,
        "--next-action-kind",
        "implement",
    )
    assert complete_rc == 0, complete
    successor_id = complete["next_todos"][0]["todo_id"]
    assert successor_id != TODO_ID

    refresh_rc, refresh = _run_cli(
        registry_path,
        runtime,
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        "--classification",
        "identity_upgrade_validated",
        "--delivery-batch-scale",
        "single_surface",
        "--delivery-outcome",
        "outcome_progress",
        *binding,
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    assert refresh_rc == 0, refresh

    successor_guard_rc, successor_guard = _run_cli(
        registry_path,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--available-capability",
        "network",
        "--scan-path",
        str(project),
    )
    assert successor_guard_rc == 0, successor_guard
    assert successor_guard["selected_todo"]["todo_id"] == successor_id

    spend_args = (
        "quota",
        "spend-slot",
        "--goal-id",
        GOAL_ID,
        "--slots",
        "1",
        "--source",
        "heartbeat",
        "--execute",
        *binding,
        "--scan-path",
        str(project),
    )
    spend_rc, spend = _run_cli(registry_path, runtime, *spend_args)
    spend_replay_rc, spend_replay = _run_cli(registry_path, runtime, *spend_args)

    assert spend_rc == 0, spend
    assert spend["settlement_result"]["ok"] is True
    assert spend_replay_rc == 0, spend_replay
    assert spend_replay["idempotent_replay"] is True
    assert spend_replay["appended"] is False
    assert _spend_run_count(runtime) == 1
    assert _heartbeat_receipt_count(runtime, TURN_ID) == 2


def test_read_only_settlement_omits_non_causal_delivery_workspace(
    tmp_path: Path,
) -> None:
    project, runtime, registry_path = _write_fixture(tmp_path)
    _configure_read_only_todo(project)
    binding = (
        "--agent-id",
        AGENT_ID,
        "--todo-id",
        TODO_ID,
        "--turn-instance-id",
        TURN_ID,
    )

    guard_rc, guard = _run_cli(
        registry_path,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--turn-instance-id",
        TURN_ID,
        "--scan-path",
        str(project),
    )
    assert guard_rc == 0, guard
    assert guard["heartbeat_receipt"]["delivery_workspace_causality"] == {
        "schema_version": "delivery_workspace_causality_v0",
        "todo_id": TODO_ID,
        "requirement": "not_required",
        "source": "selected_todo_contract",
        "reason": "explicit_non_delivery_without_repository_writes",
    }

    premature_rc, premature = _run_cli(
        registry_path,
        runtime,
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--claimed-by",
        AGENT_ID,
        "--evidence",
        "read-only characterization validated",
        "--no-follow-up",
    )
    assert premature_rc == 1, premature
    assert "requires matching writeback and quota spend receipts" in premature["error"]

    conflict_rc, conflict = _run_cli(
        registry_path,
        runtime,
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        "--classification",
        "read_only_characterization_complete",
        "--delivery-batch-scale",
        "single_surface",
        "--delivery-outcome",
        "outcome_progress",
        "--delivery-workspace-path",
        str(project),
        *binding,
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    assert conflict_rc == 1, conflict
    assert "explicit non-delivery settlement contract" in conflict["error"]

    refresh_rc, refresh = _run_cli(
        registry_path,
        runtime,
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        "--classification",
        "read_only_characterization_complete",
        "--delivery-batch-scale",
        "single_surface",
        "--delivery-outcome",
        "outcome_progress",
        *binding,
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    assert refresh_rc == 0, refresh
    assert refresh["delivery_workspace_causality"]["requirement"] == "not_required"
    assert "delivery_workspace" not in refresh

    spend_args = (
        "quota",
        "spend-slot",
        "--goal-id",
        GOAL_ID,
        "--slots",
        "1",
        "--source",
        "heartbeat",
        "--execute",
        *binding,
        "--scan-path",
        str(project),
    )
    spend_rc, spend = _run_cli(registry_path, runtime, *spend_args)
    replay_rc, replay = _run_cli(registry_path, runtime, *spend_args)

    assert spend_rc == 0, spend
    assert spend["delivery_workspace_causality"]["requirement"] == "not_required"
    assert spend["delivery_workspace_validated"] is False
    assert replay_rc == 0, replay
    assert replay["idempotent_replay"] is True
    assert _spend_run_count(runtime) == 1

    complete_rc, complete = _run_cli(
        registry_path,
        runtime,
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--claimed-by",
        AGENT_ID,
        "--evidence",
        "read-only characterization validated",
        "--no-follow-up",
    )
    assert complete_rc == 0, complete
    assert [
        receipt["step_kind"]
        for receipt in complete["settlement_result"]["receipts"]
    ] == [
        "validation",
        "durable_writeback",
        "quota_spend",
        "terminal_closeout",
    ]


def test_legacy_read_only_workspace_mismatch_fails_then_corrects_from_todo_contract(
    tmp_path: Path,
) -> None:
    project, runtime, registry_path = _write_fixture(tmp_path)
    state_path = _configure_read_only_todo(project)
    _initialize_git_checkout(project)
    binding = (
        "--agent-id",
        AGENT_ID,
        "--todo-id",
        TODO_ID,
        "--turn-instance-id",
        TURN_ID,
    )

    guard_rc, guard = _run_cli(
        registry_path,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--turn-instance-id",
        TURN_ID,
        "--scan-path",
        str(project),
    )
    assert guard_rc == 0, guard
    _strip_heartbeat_workspace_causality(runtime)

    complete_rc, complete = _run_cli(
        registry_path,
        runtime,
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        "--todo-id",
        TODO_ID,
        "--agent-id",
        AGENT_ID,
        "--claimed-by",
        AGENT_ID,
        "--evidence",
        "legacy read-only characterization validated",
        "--no-follow-up",
    )
    assert complete_rc == 0, complete

    refresh_rc, refresh = _run_cli(
        registry_path,
        runtime,
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        "--classification",
        "legacy_read_only_characterization_complete",
        "--delivery-batch-scale",
        "single_surface",
        "--delivery-outcome",
        "outcome_progress",
        "--delivery-workspace-path",
        str(project),
        *binding,
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    assert refresh_rc == 0, refresh
    assert refresh["delivery_workspace"]["workspace_kind"] == "canonical_checkout"

    causal_state = state_path.read_text(encoding="utf-8")
    state_path.write_text(
        causal_state.replace(
            "continuation_policy=same_agent_non_delivery "
            "required_capabilities=shell%2Cfilesystem_read ",
            "",
        ),
        encoding="utf-8",
    )
    spend_args = (
        "quota",
        "spend-slot",
        "--goal-id",
        GOAL_ID,
        "--slots",
        "1",
        "--source",
        "heartbeat",
        "--execute",
        *binding,
        "--scan-path",
        str(project),
    )
    failed_rc, failed = _run_cli(registry_path, runtime, *spend_args)
    assert failed_rc == 1, failed
    assert failed["workspace_guard"]["current_workspace"] == "foreign_git_worktree"
    assert _spend_run_count(runtime) == 0

    state_path.write_text(causal_state, encoding="utf-8")
    corrected_rc, corrected = _run_cli(registry_path, runtime, *spend_args)
    replay_rc, replay = _run_cli(registry_path, runtime, *spend_args)

    assert corrected_rc == 0, corrected
    assert corrected["delivery_workspace_causality"]["source"] == (
        "completed_todo_contract_fallback"
    )
    assert corrected["delivery_workspace_causality"]["requirement"] == (
        "not_required"
    )
    assert corrected["delivery_workspace_validated"] is False
    assert replay_rc == 0, replay
    assert replay["idempotent_replay"] is True
    assert [
        receipt["step_kind"] for receipt in replay["settlement_result"]["receipts"]
    ] == ["validation", "durable_writeback", "quota_spend"]
    assert _spend_run_count(runtime) == 1
