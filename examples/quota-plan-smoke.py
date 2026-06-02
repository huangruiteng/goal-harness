#!/usr/bin/env python3
"""Smoke-test multi-project quota plan ordering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.quota import (  # noqa: E402
    build_quota_plan,
    build_quota_should_run,
    build_quota_slot_preview,
    render_quota_markdown,
)


def goal(
    goal_id: str,
    *,
    compute: float,
    spent_slots: int = 0,
    allowed_slots: int | None = None,
) -> dict:
    allowed_slots = round(24 * compute) if allowed_slots is None else allowed_slots
    return {
        "id": goal_id,
        "status": "active",
        "registry_member": True,
        "lifecycle_phase": "refreshed",
        "adapter_kind": "read_only_project_map_v0",
        "adapter_status": "connected-read-only",
        "quota": {
            "compute": compute,
            "window_hours": 24,
            "allowed_slots": allowed_slots,
            "spent_slots": spent_slots,
        },
        "latest_runs": [
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "classification": "state_refreshed",
                "recommended_action": f"continue {goal_id}",
            }
        ],
    }


def attention(
    goal_id: str,
    *,
    compute: float,
    state: str = "eligible",
    waiting_on: str = "codex",
    spent_slots: int = 0,
    allowed_slots: int | None = None,
) -> dict:
    allowed_slots = round(24 * compute) if allowed_slots is None else allowed_slots
    if state == "operator_gate":
        reason = "human or target-controller gate must clear before spending compute"
    elif state == "throttled":
        reason = f"{compute:g} compute quota spent {spent_slots}/{allowed_slots} slots in this window"
    else:
        reason = f"{compute:g} compute quota; eligible for the next automatic agent turn"
    return {
        "goal_id": goal_id,
        "status": "state_refreshed" if waiting_on == "codex" else "operator_gate_deferred",
        "waiting_on": waiting_on,
        "severity": "action",
        "recommended_action": f"continue {goal_id}",
        "source": "fixture",
        "quota": {
            "compute": compute,
            "window_hours": 24,
            "allowed_slots": allowed_slots,
            "spent_slots": spent_slots,
            "state": state,
            "reason": reason,
        },
    }


def build_status_fixture() -> dict:
    goals = [
        goal("half-speed", compute=0.5),
        goal("near-limit-half", compute=0.5, spent_slots=11, allowed_slots=12),
        goal("full-speed", compute=1.0),
        goal("low-speed", compute=0.3),
        goal("throttled-half", compute=0.5, spent_slots=12, allowed_slots=12),
        goal("needs-operator", compute=1.0),
    ]
    queue_items = [
        attention("half-speed", compute=0.5),
        attention("near-limit-half", compute=0.5, spent_slots=11, allowed_slots=12),
        attention("full-speed", compute=1.0),
        attention("low-speed", compute=0.3),
        attention(
            "throttled-half",
            compute=0.5,
            state="throttled",
            spent_slots=12,
            allowed_slots=12,
        ),
        attention(
            "needs-operator",
            compute=1.0,
            state="operator_gate",
            waiting_on="user_or_controller",
        ),
    ]
    return {
        "ok": True,
        "registry": "./fixtures/registry.json",
        "runtime_root": "./fixtures/runtime",
        "goal_count": len(goals),
        "run_count": len(goals),
        "attention_queue": {"items": queue_items},
        "run_history": {"goals": goals},
    }


def write_cli_fixture(root: Path) -> tuple[Path, Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    registry_path = project / ".goal-harness" / "registry.json"
    goal_specs = [
        ("half-speed", 0.5, "state_refreshed", 0, None),
        ("near-limit-half", 0.5, "state_refreshed", 11, 12),
        ("full-speed", 1.0, "state_refreshed", 0, None),
        ("low-speed", 0.3, "state_refreshed", 0, None),
        ("throttled-half", 0.5, "state_refreshed", 12, 12),
        ("needs-operator", 1.0, "operator_gate_deferred", 0, None),
    ]
    registry_goals = []
    for goal_id, compute, classification, spent_slots, allowed_slots in goal_specs:
        state_file = f".codex/goals/{goal_id}/ACTIVE_GOAL_STATE.md"
        state_path = project / state_file
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            "---\n"
            "status: active\n"
            "updated_at: 2026-01-01T00:00:00+00:00\n"
            "---\n\n"
            f"# {goal_id}\n\n"
            "## Next Action\n\n"
            f"- continue {goal_id}\n",
            encoding="utf-8",
        )
        registry_goals.append(
            {
                "id": goal_id,
                "domain": "quota-fixture",
                "status": "active",
                "repo": str(project),
                "state_file": state_file,
                "adapter": {
                    "kind": "read_only_project_map_v0",
                    "status": "connected-read-only",
                },
                "authority_sources": [],
                "quota": {
                    key: value
                    for key, value in {
                        "compute": compute,
                        "window_hours": 24,
                        "spent_slots": spent_slots,
                        "allowed_slots": allowed_slots,
                    }.items()
                    if value is not None
                },
            }
        )
        runs_dir = runtime / "goals" / goal_id / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        json_path = runs_dir / "20260101T000000-run.json"
        markdown_path = runs_dir / "20260101T000000-run.md"
        record = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "goal_id": goal_id,
            "classification": classification,
            "recommended_action": f"continue {goal_id}",
            "health_check": "fixture 1/1",
        }
        if classification == "operator_gate_deferred":
            record["operator_gate"] = {
                "recorded_at": "2026-01-01T00:00:00+00:00",
                "gate": "read_only_map_opt_in",
                "decision": "defer",
                "operator_question": f"是否同意 `{goal_id}` 先执行 read-only map opt-in？",
                "reason_summary": "need more fixture evidence",
            }
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(f"# {goal_id} fixture run\n", encoding="utf-8")
        with (runs_dir / "index.jsonl").open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        **record,
                        "json_path": str(json_path),
                        "markdown_path": str(markdown_path),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "common_runtime_root": str(runtime),
                "goals": registry_goals,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return registry_path, runtime, project


def run_cli_quota_plan(root: Path) -> tuple[dict, str]:
    registry_path, runtime, project = write_cli_fixture(root)
    base_args = [
        sys.executable,
        "-m",
        "goal_harness.cli",
        "--registry",
        str(registry_path),
        "--runtime-root",
        str(runtime),
    ]
    json_result = subprocess.run(
        [*base_args, "--format", "json", "quota", "plan", "--scan-path", str(project)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    markdown_result = subprocess.run(
        [*base_args, "quota", "plan", "--scan-path", str(project)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(json_result.stdout), markdown_result.stdout


def run_cli_throttled_should_run(root: Path) -> dict:
    registry_path, runtime, project = write_cli_fixture(root)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime),
            "--format",
            "json",
            "quota",
            "should-run",
            "--goal-id",
            "throttled-half",
            "--scan-path",
            str(project),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def run_cli_slot_preview(root: Path) -> tuple[dict, dict]:
    registry_path, runtime, project = write_cli_fixture(root)
    base_args = [
        sys.executable,
        "-m",
        "goal_harness.cli",
        "--registry",
        str(registry_path),
        "--runtime-root",
        str(runtime),
        "--format",
        "json",
        "quota",
    ]
    preview_result = subprocess.run(
        [
            *base_args,
            "spend-slot",
            "--goal-id",
            "near-limit-half",
            "--slots",
            "1",
            "--scan-path",
            str(project),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    should_run_result = subprocess.run(
        [
            *base_args,
            "should-run",
            "--goal-id",
            "near-limit-half",
            "--scan-path",
            str(project),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(preview_result.stdout), json.loads(should_run_result.stdout)


def run_cli_slot_spend_execute(root: Path) -> dict:
    registry_path, runtime, project = write_cli_fixture(root)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime),
            "--format",
            "json",
            "quota",
            "spend-slot",
            "--goal-id",
            "near-limit-half",
            "--slots",
            "1",
            "--source",
            "heartbeat",
            "--execute",
            "--scan-path",
            str(project),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def assert_plan_shape(plan: dict, markdown: str | None = None) -> None:
    eligible_ids = [item["goal_id"] for item in plan["groups"]["eligible"]]
    operator_gate_ids = [item["goal_id"] for item in plan["groups"]["operator_gate"]]
    throttled_ids = [item["goal_id"] for item in plan["groups"]["throttled"]]

    assert plan["summary"]["next_automatic_turn"] == "full-speed", plan
    assert plan["next_automatic_turn"]["goal_id"] == "full-speed", plan
    assert eligible_ids == ["full-speed", "half-speed", "near-limit-half", "low-speed"], eligible_ids
    assert operator_gate_ids == ["needs-operator"], operator_gate_ids
    assert throttled_ids == ["throttled-half"], throttled_ids
    assert "needs-operator" not in eligible_ids, eligible_ids
    assert "throttled-half" not in eligible_ids, eligible_ids
    if markdown is not None:
        assert "next_automatic_turn=full-speed" in markdown, markdown
        assert "### operator_gate" in markdown, markdown
        assert "### throttled" in markdown, markdown
        assert "`throttled-half`" in markdown, markdown
        assert markdown.index("`full-speed`") < markdown.index("`half-speed`") < markdown.index("`near-limit-half`") < markdown.index("`low-speed`"), markdown


def assert_throttled_should_run(status_payload: dict) -> None:
    payload = build_quota_should_run(status_payload, goal_id="throttled-half")
    quota = payload["quota"]

    assert payload["ok"] is True, payload
    assert payload["decision"] == "skip", payload
    assert payload["should_run"] is False, payload
    assert payload["state"] == "throttled", payload
    assert payload["plan_summary"]["next_automatic_turn"] == "full-speed", payload
    assert quota["spent_slots"] == 12, payload
    assert quota["allowed_slots"] == 12, payload
    assert "spent 12/12" in payload["reason"], payload


def assert_throttled_cli_should_run(payload: dict) -> None:
    quota = payload["quota"]

    assert payload["ok"] is True, payload
    assert payload["goal_id"] == "throttled-half", payload
    assert payload["decision"] == "skip", payload
    assert payload["should_run"] is False, payload
    assert payload["state"] == "throttled", payload
    assert payload["waiting_on"] == "codex", payload
    assert payload["plan_summary"]["next_automatic_turn"] == "full-speed", payload
    assert quota["compute"] == 0.5, payload
    assert quota["spent_slots"] == 12, payload
    assert quota["allowed_slots"] == 12, payload
    assert "spent 12/12" in payload["reason"], payload
    assert "agent_command" not in payload, payload


def assert_slot_preview(payload: dict) -> None:
    before = payload["before"]
    after = payload["after"]

    assert payload["ok"] is True, payload
    assert payload["dry_run"] is True, payload
    assert payload["appended"] is False, payload
    assert payload["registry_mutated"] is False, payload
    assert payload["goal_id"] == "near-limit-half", payload
    assert payload["slots"] == 1, payload
    assert payload["would_throttle"] is True, payload
    assert before["state"] == "eligible", payload
    assert before["should_run"] is True, payload
    assert before["quota"]["spent_slots"] == 11, payload
    assert before["quota"]["allowed_slots"] == 12, payload
    assert after["state"] == "throttled", payload
    assert after["should_run"] is False, payload
    assert after["decision"] == "skip", payload
    assert after["quota"]["spent_slots"] == 12, payload
    assert after["quota"]["allowed_slots"] == 12, payload
    assert after["plan_summary"]["next_automatic_turn"] == "full-speed", payload


def assert_dry_run_left_cli_fixture_unchanged(payload: dict) -> None:
    assert payload["goal_id"] == "near-limit-half", payload
    assert payload["state"] == "eligible", payload
    assert payload["should_run"] is True, payload
    assert payload["quota"]["spent_slots"] == 11, payload
    assert payload["quota"]["allowed_slots"] == 12, payload


def assert_slot_spend_execute(payload: dict) -> None:
    quota_event = payload["quota_event"]
    before = quota_event["before"]
    after = quota_event["after"]
    json_path = Path(payload["json_path"])
    index_path = Path(payload["index_path"])

    assert payload["ok"] is True, payload
    assert payload["dry_run"] is False, payload
    assert payload["appended"] is True, payload
    assert payload["registry_mutated"] is False, payload
    assert payload["classification"] == "quota_slot_spent", payload
    assert payload["source"] == "heartbeat", payload
    assert json_path.exists(), payload
    assert index_path.exists(), payload
    assert quota_event["event_type"] == "quota_slot_spent", payload
    assert quota_event["slots"] == 1, payload
    assert before["should_run"] is True, payload
    assert before["state"] == "eligible", payload
    assert before["spent_slots"] == 11, payload
    assert after["spent_slots"] == 12, payload
    assert after["allowed_slots"] == 12, payload
    assert after["state"] == "throttled", payload
    assert after["should_run"] is False, payload

    record = json.loads(json_path.read_text(encoding="utf-8"))
    assert record["classification"] == "quota_slot_spent", record
    assert record["quota_event"] == quota_event, record
    forbidden = {"human_reward", "operator_gate", "write_control", "private_evidence", "agent_command"}
    assert forbidden.isdisjoint(record), record
    assert forbidden.isdisjoint(record["quota_event"]), record
    index_lines = index_path.read_text(encoding="utf-8").splitlines()
    assert any('"classification": "quota_slot_spent"' in line for line in index_lines), index_lines


def main() -> int:
    status_payload = build_status_fixture()
    plan = build_quota_plan(status_payload, mode="plan")
    markdown = render_quota_markdown(plan)
    assert_plan_shape(plan, markdown)
    assert_throttled_should_run(status_payload)
    assert_slot_preview(build_quota_slot_preview(status_payload, goal_id="near-limit-half", slots=1))
    with tempfile.TemporaryDirectory(prefix="goal-harness-quota-plan-smoke-") as tmp:
        cli_plan, cli_markdown = run_cli_quota_plan(Path(tmp))
    assert_plan_shape(cli_plan, cli_markdown)
    with tempfile.TemporaryDirectory(prefix="goal-harness-quota-should-run-smoke-") as tmp:
        assert_throttled_cli_should_run(run_cli_throttled_should_run(Path(tmp)))
    with tempfile.TemporaryDirectory(prefix="goal-harness-quota-slot-smoke-") as tmp:
        slot_preview, should_run_after_preview = run_cli_slot_preview(Path(tmp))
    assert_slot_preview(slot_preview)
    assert_dry_run_left_cli_fixture_unchanged(should_run_after_preview)
    with tempfile.TemporaryDirectory(prefix="goal-harness-quota-slot-execute-smoke-") as tmp:
        assert_slot_spend_execute(run_cli_slot_spend_execute(Path(tmp)))
    print("quota-plan-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
