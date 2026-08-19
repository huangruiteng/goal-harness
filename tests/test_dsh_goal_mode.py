from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from loopx import dsh_goal_mode
from loopx.control_plane.quota.turn_envelope import (
    turn_envelope_action_signature_document,
)
from loopx.dsh_goal_mode import turn_host_adapter

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPAT_LAUNCHER = REPO_ROOT / "scripts" / "dsh_turn_host_adapter.py"
TURN_KEY = "sha256:" + "0" * 64


def _signed_request(
    *,
    primary_action: str = "Do the signed thing.",
) -> dict:
    request = {
        "schema_version": dsh_goal_mode.LOOPX_TURN_HOST_REQUEST_SCHEMA,
        "turn_key": TURN_KEY,
        "route": "primary_delivery",
        "session": {"goal_id": "g", "agent_id": "a"},
        "turn_envelope": {
            "schema_version": "loopx_turn_envelope_v0",
            "goal_id": "g",
            "agent_id": "a",
            "action": {
                "recommended_action": "legacy action must not win",
                "primary_action": primary_action,
                "must_attempt": True,
            },
            "required_reads": [
                {
                    "kind": "command",
                    "command": "git status --short",
                    "reason": "establish the workspace baseline",
                }
            ],
            "boundary": {
                "write_scope": ["docs/**", "tests/**"],
                "workspace_guard": {
                    "schema_version": "workspace_guard_v0",
                    "status": "ready",
                    "action": "continue",
                },
            },
            "action_signature": {
                "schema_version": "loopx_action_signature_v0",
                "matches": True,
            },
        },
        "result_contract": {
            "schema_version": dsh_goal_mode.LOOPX_TURN_RESULT_SCHEMA,
            "completed_phases": list(dsh_goal_mode.COMPLETED_PHASES),
        },
    }
    signature = turn_envelope_action_signature_document(
        request["turn_envelope"]
    )
    signature_hash = "sha256:" + sha256(
        json.dumps(
            signature,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request["turn_envelope"]["action_signature"].update(
        {
            "source_hash": signature_hash,
            "envelope_hash": signature_hash,
        }
    )
    return request


def test_dsh_goal_mode_is_a_first_class_subpackage() -> None:
    # The subpackage owns the adapter constants and API surface, following the
    # pi/opencode/kunluncode goal-mode packaging pattern.
    assert dsh_goal_mode.ADAPTER_MODULE == "loopx.dsh_goal_mode"
    assert dsh_goal_mode.LOOPX_TURN_HOST_REQUEST_SCHEMA == "loopx_turn_host_request_v0"
    assert dsh_goal_mode.LOOPX_TURN_RESULT_SCHEMA == "loopx_turn_result_v0"
    assert callable(dsh_goal_mode.main)
    for name in (
        "build_result",
        "extract_action_text",
        "extract_turn_authority",
        "load_dsh_runner",
        "parse_model_json",
        "render_prompt",
        "run_dsh_turn",
    ):
        assert callable(getattr(dsh_goal_mode, name)), name


def test_legacy_script_is_a_compat_shim_for_the_subpackage() -> None:
    # The historical loose script must keep importing (examples add scripts/
    # to sys.path) and resolve to the very same implementation objects.
    spec = importlib.util.spec_from_file_location(
        "dsh_turn_host_adapter_compat", COMPAT_LAUNCHER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in dsh_goal_mode.__all__:
        if name in {"ADAPTER_MODULE", "COMPAT_LAUNCHER"}:
            continue
        assert getattr(module, name) is getattr(dsh_goal_mode, name), name


def test_signed_primary_action_is_the_bounded_task_body() -> None:
    request = _signed_request(primary_action="signed primary action")
    assert turn_host_adapter.extract_action_text(request) == "signed primary action"


def test_unsigned_action_fails_closed() -> None:
    request = _signed_request()
    request["turn_envelope"]["action_signature"]["matches"] = False
    try:
        turn_host_adapter.extract_action_text(request)
    except ValueError as exc:
        assert "action signature" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("unsigned TurnEnvelope action must fail closed")


def test_prompt_requests_one_typed_public_safe_json_result() -> None:
    request = _signed_request()
    authority = turn_host_adapter.extract_turn_authority(request)
    prompt = turn_host_adapter.render_prompt(authority)
    assert "primary_action" in prompt
    assert "result_kind" in prompt
    assert "validated_progress" in prompt
    # Boundary discipline stays in the prompt text.
    assert "write_scope" in prompt
    assert "credentials" in prompt


def test_parse_model_json_tolerates_prose_and_fences() -> None:
    payload = {"result_kind": "wait", "summary": "nothing to do"}
    assert turn_host_adapter.parse_model_json(json.dumps(payload)) == payload
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert turn_host_adapter.parse_model_json(fenced) == payload
    prose = f"Here is the result you asked for:\n{json.dumps(payload)}\nDone."
    assert turn_host_adapter.parse_model_json(prose) == payload
    assert turn_host_adapter.parse_model_json("") is None
    assert turn_host_adapter.parse_model_json("no json at all") is None


def test_build_result_fails_closed_without_a_typed_candidate() -> None:
    request = _signed_request()
    result = turn_host_adapter.build_result(request, None)
    assert result["schema_version"] == dsh_goal_mode.LOOPX_TURN_RESULT_SCHEMA
    assert result["turn_key"] == TURN_KEY
    assert result["result_kind"] == "wait"
    assert result["completed_phases"] == ["host_execute", "typed_result"]
    assert result["classification"] == "no_typed_host_result"


def test_build_result_rejects_unsupported_result_kinds() -> None:
    request = _signed_request()
    result = turn_host_adapter.build_result(
        request, {"result_kind": "goal_complete", "summary": "host says done"}
    )
    assert result["result_kind"] == "wait"
    assert result["classification"] == "unsupported_host_result_kind"


def test_build_result_shapes_material_results_with_required_fields() -> None:
    request = _signed_request()
    result = turn_host_adapter.build_result(
        request,
        {
            "result_kind": "validated_progress",
            "classification": "docs updated",
            "summary": "one change",
            "next_action": "review the diff",
        },
    )
    assert result["result_kind"] == "validated_progress"
    assert result["delivery_batch_scale"] == "single_surface"
    assert result["delivery_outcome"] == "outcome_progress"
    # Sparse material blocks get bounded fallbacks, never empty authority text.
    assert result["recommended_action"]
    assert result["vision_unchanged_reason"]


def test_adapter_runs_hermetically_through_the_module_entry() -> None:
    # `python -m loopx.dsh_goal_mode` must drive the same stdin/stdout
    # contract as the legacy script, using a fake dsh runner.
    runner = Path(__file__).parent / "dsh_goal_mode_fake_runner.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.dsh_goal_mode",
            "--dsh-runner",
            str(runner),
        ],
        input=json.dumps(_signed_request()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == dsh_goal_mode.LOOPX_TURN_RESULT_SCHEMA
    assert result["result_kind"] == "validated_progress"
    assert result["classification"] == "fake dsh typed result"


def test_legacy_launcher_runs_the_same_contract() -> None:
    runner = Path(__file__).parent / "dsh_goal_mode_fake_runner.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(COMPAT_LAUNCHER),
            "--dsh-runner",
            str(runner),
        ],
        input=json.dumps(_signed_request()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == dsh_goal_mode.LOOPX_TURN_RESULT_SCHEMA
    assert result["result_kind"] == "validated_progress"
