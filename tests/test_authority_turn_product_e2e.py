from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane.coordination.file_provider import FileCoordinationProvider
from loopx.control_plane.coordination.head import bootstrap_head
from loopx.extensions.runtime import default_extension_state_file, install_extension


REPOSITORY = Path(__file__).resolve().parents[1]
GOAL_ID = "goal-authority-product-e2e"
TODO_ID = "todo_authority_product_e2e"
FOLLOWUP_TODO_ID = "todo_authority_product_followup"
AGENT_IDS = ("agent-a", "agent-b")


def _write_product_fixture(
    root: Path,
    *,
    include_todo: bool = True,
) -> tuple[Path, Path, Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    host_project = root / "shared-host-project"
    runtime.mkdir(parents=True)
    host_project.mkdir()
    state = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state.parent.mkdir(parents=True)
    todo_lines = (
        [
            "- [ ] [P0] Advance the authority-qualified product fixture.",
            "  <!-- loopx:todo "
            f"todo_id={TODO_ID} status=open task_class=advancement_task "
            "action_kind=fixture priority=P0 "
            f"successor_todo_ids={FOLLOWUP_TODO_ID} -->",
            "",
            "- [ ] [P2] Keep the follow-up fixture available.",
            "  <!-- loopx:todo "
            f"todo_id={FOLLOWUP_TODO_ID} status=open "
            "task_class=advancement_task action_kind=fixture priority=P2 -->",
            "",
        ]
        if include_todo
        else []
    )
    state.write_text(
        "\n".join(
            [
                "---",
                "status: active",
                "updated_at: 2026-09-02T00:00:00+00:00",
                "---",
                "",
                "# Authority Product E2E",
                "",
                "## Agent Todo",
                "",
                *todo_lines,
            ]
        ),
        encoding="utf-8",
    )
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "loopx-authority-product-fixture",
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state.relative_to(project)),
                        "adapter": {
                            "kind": "fixture_v0",
                            "status": "connected-delivery",
                        },
                        "quota": {"compute": 2.0, "window_hours": 24},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": list(AGENT_IDS),
                            "agent_profiles": {
                                agent_id: {
                                    "schema_version": "agent_profile_v1",
                                    "profile_role": "fixture",
                                    "scope": "public qualification",
                                }
                                for agent_id in AGENT_IDS
                            },
                            "write_scope": ["docs/**"],
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return project, runtime, registry, host_project


def _bootstrap_authority(store: Path) -> None:
    provider = FileCoordinationProvider(store, GOAL_ID)
    head = bootstrap_head(
        GOAL_ID,
        {
            TODO_ID: {
                "todo_revision": 1,
                "status": "open",
                "claimed_by": None,
                "eligibility": {
                    "authorization_projection_revision": 1,
                    "authorization_projection_digest": "sha256:product-e2e",
                    "allowed_agent_ids": list(AGENT_IDS),
                    "dependencies_satisfied": True,
                    "dependency_revision": 1,
                    "gates_open": True,
                    "gate_revision": 1,
                },
                "repository": "git:example/authority-product-e2e",
                "code_revision": "0123456789abcdef",
                "last_lease_epoch": 0,
            }
        },
        store_binding=provider.store_identity(),
    )
    assert provider.compare_and_put(0, head)["result"] == "applied"


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env["LOOPX_SHARED_AUTHORITY_TEST_ONLY"] = "1"
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPOSITORY), python_path) if part
    )
    return env


def _run_cli(*args: str, timeout: float = 60) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        cwd=REPOSITORY,
        env=_cli_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    assert completed.stdout, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def _common_cli_args(registry: Path, runtime: Path) -> list[str]:
    return [
        "--registry",
        str(registry),
        "--runtime-root",
        str(runtime),
        "--format",
        "json",
    ]


def _guard_argv(
    *,
    store: Path,
    clock: Path,
    barrier: Path,
    barrier_helper: Path,
    agent_id: str,
) -> list[str]:
    delegate = [
        sys.executable,
        str(REPOSITORY / "examples" / "nokv-shadow-provider" / "authority_guard.py"),
        "--store-directory",
        str(store),
        "--clock-file",
        str(clock),
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        agent_id,
        "--todo-id",
        TODO_ID,
        "--lease-ttl-seconds",
        "60",
        "--reclaim-grace-seconds",
        "3",
    ]
    return [
        sys.executable,
        str(barrier_helper),
        str(barrier),
        agent_id,
        *delegate,
    ]


HOST_SCRIPT = """
import json
import os
import pathlib
import sys
import time

request = json.load(sys.stdin)
agent_id = request["turn_envelope"]["agent_id"]
log_path = pathlib.Path(sys.argv[1])
descriptor = os.open(log_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
try:
    os.write(descriptor, (json.dumps({"agent_id": agent_id}) + "\\n").encode())
finally:
    os.close(descriptor)
time.sleep(0.75)
json.dump({
    "schema_version": "loopx_turn_result_v0",
    "turn_key": request["turn_key"],
    "result_kind": "validated_completion",
    "completed_phases": ["host_execute", "typed_result"],
    "classification": "authority_product_completion",
    "recommended_action": "Continue the authority-qualified product fixture.",
    "next_action": "Run the next authority-qualified product check.",
    "delivery_batch_scale": "implementation",
    "delivery_outcome": "outcome_progress",
    "vision_unchanged_reason": "The qualification objective remains unchanged.",
    "summary": "One product CLI Turn completed after shared-authority admission."
}, sys.stdout)
"""


VALIDATOR_SCRIPT = """
import json
import pathlib
import sys

result = json.load(sys.stdin)
rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text().splitlines()]
raise SystemExit(0 if len(rows) == 1 and result["result_kind"] == "validated_completion" else 7)
"""


GUARD_BARRIER_SCRIPT = """
import json
import pathlib
import subprocess
import sys
import time

raw_request = sys.stdin.read()
request = json.loads(raw_request)
barrier = pathlib.Path(sys.argv[1])
agent_id = sys.argv[2]
delegate = sys.argv[3:]
if request.get("checkpoint") == "host_admission":
    barrier.mkdir(parents=True, exist_ok=True)
    (barrier / agent_id).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 20
    while len(list(barrier.iterdir())) < 2:
        if time.monotonic() >= deadline:
            raise SystemExit(72)
        time.sleep(0.01)
completed = subprocess.run(delegate, input=raw_request, text=True, capture_output=True)
sys.stdout.write(completed.stdout)
raise SystemExit(completed.returncode)
"""


def _write_process_helpers(root: Path) -> tuple[Path, Path, Path]:
    host = root / "typed_host.py"
    validator = root / "independent_validator.py"
    guard_barrier = root / "authority_guard_barrier.py"
    host.write_text(HOST_SCRIPT, encoding="utf-8")
    validator.write_text(VALIDATOR_SCRIPT, encoding="utf-8")
    guard_barrier.write_text(GUARD_BARRIER_SCRIPT, encoding="utf-8")
    return host, validator, guard_barrier


def _configure_live_inbox_signal(
    *, project: Path, runtime: Path, registry: Path, root: Path
) -> None:
    provider = root / "extension_provider.py"
    provider.write_text(
        """#!/usr/bin/env python3
import sys

raise SystemExit(0 if "--doctor" in sys.argv else 0)
""",
        encoding="utf-8",
    )
    provider.chmod(0o755)
    manifest = root / "lark-extension.toml"
    permissions = [
        "lark.collector.manage",
        "lark.inbox.read",
        "lark.inbox.write",
    ]
    manifest.write_text(
        "\n".join(
            [
                'schema_version = "loopx_extension_manifest_v0"',
                'id = "loopx-lark"',
                'version = "0.0.0-test"',
                'requires_loopx_api = ">=1,<2"',
                f"permissions = {json.dumps(permissions)}",
                "",
                "[runtime]",
                'protocol = "lark_test_activation_v0"',
                f"entrypoint = {json.dumps(str(provider))}",
                'doctor_args = ["--doctor"]',
                f"required_permissions = {json.dumps(permissions)}",
                "timeout_seconds = 5",
                "",
            ]
        ),
        encoding="utf-8",
    )
    install_extension(
        manifest,
        state_file=default_extension_state_file(runtime),
        execute=True,
    )

    config_relative = Path(".loopx/config/lark/product-e2e.json")
    config = project / config_relative
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": ".loopx/inbox/live-steering",
                "capture_scope": "configured_chat_all",
                "reply": {
                    "enabled": True,
                    "sender_profile": "product-fixture-bot",
                    "sender_identity": "bot",
                    "bot_display_name": "LoopX",
                    "chat_id": "oc_product_fixture",
                    "placement_policy": "source_context",
                    "editorial_style": "bullet_points_preferred",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    digest = "sha256:" + hashlib.sha256(config.read_bytes()).hexdigest()
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))
    registry_payload["goals"][0]["control_plane"] = {
        "lark_event_inbox": {
            "enabled": True,
            "config_path": str(config_relative),
            "config_digest": digest,
        }
    }
    registry.write_text(
        json.dumps(registry_payload, indent=2) + "\n",
        encoding="utf-8",
    )


def test_two_product_cli_agents_share_one_authority_and_settle_once(
    tmp_path: Path,
) -> None:
    project, runtime, registry, host_project = _write_product_fixture(tmp_path)
    store = tmp_path / "authority-store"
    clock = tmp_path / "authority-clock"
    host_log = tmp_path / "host.jsonl"
    host_helper, validator_helper, barrier_helper = _write_process_helpers(tmp_path)
    admission_barrier = tmp_path / "admission-barrier"
    clock.write_text("1000", encoding="utf-8")
    _bootstrap_authority(store)

    status_exit, status = _run_cli(
        *_common_cli_args(registry, runtime),
        "status",
        "--goal-id",
        GOAL_ID,
        "--scan-root",
        str(project),
    )
    assert status_exit == 0, status
    assert status["ok"] is True

    quota_exit, quota = _run_cli(
        *_common_cli_args(registry, runtime),
        "quota",
        "should-run",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_IDS[0],
        "--host-surface",
        "generic_cli",
        "--scheduler-owner",
        "outer_controller",
        "--execution-mode",
        "isolated_headless",
        "--scan-root",
        str(project),
    )
    assert quota_exit == 0, quota
    assert quota["should_run"] is True
    assert quota["selected_todo"]["todo_id"] == TODO_ID

    plan_exit, plan = _run_cli(
        *_common_cli_args(registry, runtime),
        "turn",
        "plan",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_IDS[0],
        "--host",
        "generic-cli",
        "--scheduler-owner",
        "outer_controller",
        "--execution-mode",
        "isolated-headless",
        "--scan-root",
        str(project),
    )
    assert plan_exit == 0, plan
    assert plan["route"]["kind"] == "ready_for_host"
    envelope = plan["turn_envelope"]
    assert envelope["schema_version"] == "loopx_turn_envelope_v0"
    assert envelope["action_signature"]["matches"] is True
    selected_todo = envelope["action"]["selected_todo"]
    assert selected_todo["todo_id"] == TODO_ID
    assert selected_todo["selected_by"] == "turn_controller_advisory_primary"
    assert (
        envelope["action"]["action_portfolio"]["selection_policy"][
            "requires_explicit_turn_binding"
        ]
        is True
    )

    processes: list[subprocess.Popen[str]] = []
    argv_by_agent: dict[str, list[str]] = {}
    for agent_id in AGENT_IDS:
        argv = [
            sys.executable,
            "-m",
            "loopx.cli",
            *_common_cli_args(registry, runtime),
            "turn",
            "run-once",
            "--goal-id",
            GOAL_ID,
            "--agent-id",
            agent_id,
            "--turn-instance-id",
            f"product-e2e-{agent_id}",
            "--project",
            str(host_project),
            "--host-adapter-command-json",
            json.dumps([sys.executable, str(host_helper), str(host_log)]),
            "--validation-command-json",
            json.dumps([sys.executable, str(validator_helper), str(host_log)]),
            "--authority-guard-command-json",
            json.dumps(
                _guard_argv(
                    store=store,
                    clock=clock,
                    barrier=admission_barrier,
                    barrier_helper=barrier_helper,
                    agent_id=agent_id,
                )
            ),
            "--scan-root",
            str(project),
            "--no-global-sync",
            "--execute",
        ]
        processes.append(
            subprocess.Popen(
                argv,
                cwd=REPOSITORY,
                env=_cli_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )
        argv_by_agent[agent_id] = argv

    completed = [process.communicate(timeout=60) for process in processes]
    results = [json.loads(stdout) for stdout, _stderr in completed]
    assert sorted(process.returncode for process in processes) == [0, 1], completed
    committed = [result for result in results if result.get("status") == "committed"]
    rejected = [
        result
        for result in results
        if result.get("result_kind") == "authority_rejected"
    ]
    assert len(committed) == 1, results
    assert len(rejected) == 1, results
    assert committed[0]["validation"]["status"] == "passed"
    assert committed[0]["validation"]["validator_kind"] == "command"
    assert committed[0]["receipt"]["status"] == "committed"
    assert committed[0]["receipt"]["next_phase"] is None
    assert committed[0]["scheduler"]["completed"] is True
    assert {
        checkpoint: receipt["status"]
        for checkpoint, receipt in committed[0]["authority_checkpoint_guard"][
            "checkpoints"
        ].items()
    } == {
        "host_admission": "accepted",
        "durable_writeback": "accepted",
        "quota_spend": "accepted",
        "scheduler": "accepted",
        "authority_complete": "accepted",
    }
    assert committed[0]["effects"] == {
        "host_invoked": True,
        "state_written": True,
        "quota_spent": True,
        "scheduler_acknowledged": False,
    }
    assert rejected[0]["effects"] == {
        "host_invoked": False,
        "state_written": False,
        "quota_spent": False,
        "scheduler_acknowledged": False,
    }
    assert rejected[0]["receipt"]["failed_phase"] == "authority_admission"
    assert (
        rejected[0]["authority_checkpoint_guard"]["checkpoints"]["host_admission"][
            "status"
        ]
        == "rejected"
    )

    host_rows = [json.loads(line) for line in host_log.read_text().splitlines()]
    assert len(host_rows) == 1
    index = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"
    run_rows = [json.loads(line) for line in index.read_text().splitlines()]
    assert [row["classification"] for row in run_rows] == [
        "authority_product_completion",
        "quota_slot_spent",
    ]
    state = (project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md").read_text(
        encoding="utf-8"
    )
    assert state.count(f"todo_id={TODO_ID} status=done") == 1
    journals = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (runtime / "goals" / GOAL_ID / "turns").glob("*.json")
    ]
    assert sorted(journal["status"] for journal in journals) == [
        "committed",
        "failed",
    ]

    winning_agent_id = committed[0]["receipt"]["lineage"]["agent_id"]
    replay_argv = list(argv_by_agent[winning_agent_id])
    turn_instance_index = replay_argv.index("--turn-instance-id")
    del replay_argv[turn_instance_index : turn_instance_index + 2]
    replay_argv.extend(["--resume-turn-key", committed[0]["resume_turn_key"]])
    provider = FileCoordinationProvider(store, GOAL_ID)
    _head_before_replay, generation_before_replay = provider.load()
    artifacts_before_replay = {
        "host": host_log.read_text(encoding="utf-8"),
        "runs": index.read_text(encoding="utf-8"),
        "state": state,
        "rollout": (runtime / "goals" / GOAL_ID / "rollout-event-log.jsonl").read_text(
            encoding="utf-8"
        ),
    }
    replay_completed = subprocess.run(
        replay_argv,
        cwd=REPOSITORY,
        env=_cli_env(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    replay = json.loads(replay_completed.stdout)
    assert replay_completed.returncode == 0, replay
    assert replay["status"] == "committed"
    assert replay["effects"] == {
        "host_invoked": False,
        "state_written": False,
        "quota_spent": False,
        "scheduler_acknowledged": False,
    }
    _head_after_replay, generation_after_replay = provider.load()
    assert generation_after_replay == generation_before_replay
    assert host_log.read_text(encoding="utf-8") == artifacts_before_replay["host"]
    assert index.read_text(encoding="utf-8") == artifacts_before_replay["runs"]
    assert (project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md").read_text(
        encoding="utf-8"
    ) == artifacts_before_replay["state"]
    assert (runtime / "goals" / GOAL_ID / "rollout-event-log.jsonl").read_text(
        encoding="utf-8"
    ) == artifacts_before_replay["rollout"]

    authority_head, _generation = provider.load()
    assert authority_head is not None
    authority_todo = authority_head["coordination"]["todos"][TODO_ID]
    assert authority_todo["status"] == "done"
    assert TODO_ID not in authority_head["coordination"]["leases"]
    completion_receipts = [
        entry["original_receipt"]
        for entry in authority_head["receipt_index"].values()
        if entry["original_receipt"]["command"] == "complete_work"
    ]
    assert len(completion_receipts) == 1
    assert completion_receipts[0]["actor"]["agent_id"] == winning_agent_id


def test_configured_inbox_signal_cannot_grant_todo_or_turn_authority(
    tmp_path: Path,
) -> None:
    project, runtime, registry, _host_project = _write_product_fixture(
        tmp_path,
        include_todo=False,
    )
    inbox = project / ".loopx" / "inbox" / "live-steering"
    inbox.mkdir(parents=True)
    (inbox / "pending.json").write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_event_v0",
                "event_id": "evt_product_e2e",
                "message_id": "om_product_e2e",
                "create_time": "2026-09-02T00:00:00Z",
                "content": "@LoopX continue this project",
                "addressed_to_bot": True,
                "attachment_count": 0,
            }
        ),
        encoding="utf-8",
    )
    _configure_live_inbox_signal(
        project=project,
        runtime=runtime,
        registry=registry,
        root=tmp_path,
    )

    plan_exit, plan = _run_cli(
        *_common_cli_args(registry, runtime),
        "turn",
        "plan",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_IDS[0],
        "--host",
        "generic-cli",
        "--scheduler-owner",
        "outer_controller",
        "--execution-mode",
        "isolated-headless",
        "--scan-root",
        str(project),
    )
    # Inbox/steering is an urgency signal, not a Todo or execution-authority
    # source. With no durable selected Todo, the product Turn fails closed at
    # lineage planning instead of admitting Host work.
    assert plan_exit == 1, plan
    assert plan["route"]["kind"] == "contract_error"
    assert plan["turn_envelope"]["should_run"] is True
    assert plan["turn_envelope"]["effective_action"] == "lark_inbox_reply_due"
    assert plan["route"]["selected_todo"] is None
    assert plan["turn_envelope"]["action"]["selected_todo"] is None
    assert plan["route"]["would_invoke_host"] is False
    assert plan["effects"]["host_invoked"] is False
    assert "authority_checkpoint_guard" not in plan
    assert not (runtime / "goals" / GOAL_ID / "turns").exists()


def _remove_live_nokv_head(provider: Any) -> None:
    head, generation = provider.load()
    if head is None:
        return
    result = provider.client.remove(
        provider.workbench,
        provider.head_path,
        generation,
    )
    if not isinstance(result, dict) or result.get("removed") is not True:
        raise AssertionError("live NoKV product E2E did not remove its test head")


@pytest.mark.skipif(
    os.environ.get("NOKV_COORDINATION_LIVE") != "1",
    reason="set NOKV_COORDINATION_LIVE=1 for the opt-in NoKV product E2E",
)
def test_two_product_cli_agents_share_one_live_nokv_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path_value = os.environ.get("NOKV_CLIENT_CONFIG_JSON", "")
    workbench = os.environ.get("NOKV_COORDINATION_WORKBENCH", "")
    config_path = Path(config_path_value)
    if not config_path.is_absolute() or not config_path.is_file() or not workbench:
        pytest.fail(
            "live NoKV product E2E requires an absolute NOKV_CLIENT_CONFIG_JSON "
            "and NOKV_COORDINATION_WORKBENCH"
        )

    provider_directory = REPOSITORY / "examples" / "nokv-shadow-provider"
    sys.path.insert(0, str(provider_directory))
    try:
        from provider import open_nokv_coordination_provider
    finally:
        sys.path.pop(0)
    from loopx.control_plane.coordination.nokv_jsonl_helper import build_client

    config = json.loads(config_path.read_text(encoding="utf-8"))
    suffix = uuid.uuid4().hex[:12]
    goal_id = f"goal-authority-product-live-{suffix}"
    todo_id = f"todo_{suffix}"
    followup_todo_id = f"follow_{suffix}"

    def open_provider(_directory: Path, selected_goal_id: str):
        return open_nokv_coordination_provider(
            lambda: build_client(config),
            workbench,
            selected_goal_id,
        )

    def live_guard_argv(
        *,
        store: Path,
        clock: Path,
        barrier: Path,
        barrier_helper: Path,
        agent_id: str,
    ) -> list[str]:
        del store
        delegate = [
            sys.executable,
            str(provider_directory / "authority_guard.py"),
            "--nokv-client-config-json",
            str(config_path),
            "--nokv-workbench",
            workbench,
            "--clock-file",
            str(clock),
            "--goal-id",
            goal_id,
            "--agent-id",
            agent_id,
            "--todo-id",
            todo_id,
            "--lease-ttl-seconds",
            "60",
            "--reclaim-grace-seconds",
            "3",
        ]
        return [
            sys.executable,
            str(barrier_helper),
            str(barrier),
            agent_id,
            *delegate,
        ]

    module = sys.modules[__name__]
    monkeypatch.setattr(module, "GOAL_ID", goal_id)
    monkeypatch.setattr(module, "TODO_ID", todo_id)
    monkeypatch.setattr(module, "FOLLOWUP_TODO_ID", followup_todo_id)
    monkeypatch.setattr(module, "FileCoordinationProvider", open_provider)
    monkeypatch.setattr(module, "_guard_argv", live_guard_argv)

    cleanup_provider = open_provider(Path(), goal_id)
    completed = False
    try:
        test_two_product_cli_agents_share_one_authority_and_settle_once(tmp_path)
        completed = True
    finally:
        try:
            _remove_live_nokv_head(cleanup_provider)
        except Exception:
            if completed:
                raise
