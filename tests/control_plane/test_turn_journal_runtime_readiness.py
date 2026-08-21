from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane import effect_runtime
from loopx.doctor import collect_doctor, render_doctor_markdown


class _Completed:
    def __init__(self, *, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def test_runtime_fingerprint_rotates_when_any_owned_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = Path(effect_runtime.__file__).resolve().parent
    for relative in effect_runtime._SOURCE_FILES:
        source = source_root / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    monkeypatch.setattr(effect_runtime, "_control_plane_root", lambda: tmp_path)

    effect_runtime._runtime_fingerprint.cache_clear()
    original = effect_runtime._runtime_fingerprint()
    for index, relative in enumerate(effect_runtime._SOURCE_FILES):
        target = tmp_path / relative
        original_bytes = target.read_bytes()
        target.write_bytes(original_bytes + f"\n// fingerprint-{index}\n".encode())
        effect_runtime._runtime_fingerprint.cache_clear()
        assert effect_runtime._runtime_fingerprint() != original
        target.write_bytes(original_bytes)
    effect_runtime._runtime_fingerprint.cache_clear()
    assert effect_runtime._runtime_fingerprint() == original


def test_missing_node_blocks_the_typescript_control_plane_and_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(effect_runtime.shutil, "which", lambda _name: None)

    result = effect_runtime.collect_effect_runtime_readiness()

    assert result["status"] == "missing"
    assert result["ready"] is False
    assert result["default_cli_blocking"] is True
    assert result["required_for"] == ["control_plane"]
    assert "Node.js 22.6.0 or newer" in str(result["recommended_action"])


def test_old_node_is_reported_without_running_semantic_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(effect_runtime.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(
        effect_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: _Completed(stdout="v20.19.5\n"),
    )

    result = effect_runtime.collect_effect_runtime_readiness(deep=True)

    assert result["status"] == "unsupported"
    assert result["detected_node_version"] == "20.19.5"
    assert result["semantic_probe"] == "not_run"


def test_current_node_standard_probe_does_not_execute_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(effect_runtime.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(
        effect_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: _Completed(stdout="v22.6.0\n"),
    )

    result = effect_runtime.collect_effect_runtime_readiness()

    assert result["status"] == "ready"
    assert result["ready"] is True
    assert result["semantic_probe"] == "not_requested"
    assert result["runtime_lifecycle"] == {
        "schema_version": "loopx_effect_runtime_lifecycle_v0",
        "management": "on_demand_managed",
        "state": "stopped",
        "manual_start_required": False,
        "restart_policy": "automatic_on_next_control_plane_request",
        "idle_shutdown": True,
        "diagnostic_code": None,
    }


def test_deep_probe_executes_packaged_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(effect_runtime.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(
        effect_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: _Completed(stdout="v24.1.0\n"),
    )

    def request(method: str, params: dict[str, Any]) -> dict[str, object]:
        calls.append((method, params))
        if method == "runtime.ping":
            return {"ready": True}
        return {"effect_id": "doctor-probe:doctor-probe:doctor-probe:doctor-probe"}

    monkeypatch.setattr(
        effect_runtime,
        "effect_runtime_result",
        request,
    )

    result = effect_runtime.collect_effect_runtime_readiness(deep=True)

    assert result["status"] == "ready"
    assert result["semantic_probe"] == "passed"
    assert result["runtime_lifecycle"]["state"] == "running"
    assert [method for method, _params in calls] == [
        "runtime.ping",
        "settlement.identity",
    ]
    assert calls[1][1]["goal_id"] == "doctor-probe"


def test_deep_probe_failure_is_public_safe_and_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(effect_runtime.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(
        effect_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: _Completed(stdout="v22.6.0\n"),
    )

    def failed(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise effect_runtime.EffectRuntimeStartupError(
            "/private/path/worker.mjs failed",
            diagnostic_code="runtime_exited_before_ready",
        )

    monkeypatch.setattr(
        effect_runtime,
        "effect_runtime_result",
        failed,
    )

    result = effect_runtime.collect_effect_runtime_readiness(deep=True)

    assert result["status"] == "probe_failed"
    assert result["ready"] is False
    assert result["semantic_probe"] == "failed"
    assert "/private/path" not in str(result)
    assert "reinstall LoopX" in str(result["recommended_action"])
    assert result["runtime_lifecycle"]["state"] == "unavailable"
    assert (
        result["runtime_lifecycle"]["diagnostic_code"]
        == "runtime_exited_before_ready"
    )


def test_doctor_markdown_projects_runtime_lifecycle_for_app_health() -> None:
    rendered = render_doctor_markdown(
        {
            "typescript_control_plane": {
                "status": "probe_failed",
                "runtime_lifecycle": {
                    "state": "unavailable",
                    "diagnostic_code": "runtime_exited_before_ready",
                },
            },
            "checks": [],
        }
    )

    assert "typescript_runtime_state: `unavailable`" in rendered
    assert (
        "typescript_runtime_diagnostic: `runtime_exited_before_ready`" in rendered
    )


def test_missing_required_runtime_fails_doctor_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = {
        "schema_version": "loopx_effect_runtime_readiness_v0",
        "ready": True,
        "status": "ready",
        "required_for": ["control_plane"],
        "default_cli_blocking": True,
        "minimum_node_version": "22.6.0",
        "detected_node_version": "24.1.0",
        "semantic_probe": "not_requested",
        "recommended_action": None,
    }
    missing = {
        **ready,
        "ready": False,
        "status": "missing",
        "detected_node_version": None,
        "recommended_action": "Install Node.js 22.6.0 or newer.",
    }
    monkeypatch.setattr(
        effect_runtime,
        "collect_effect_runtime_readiness",
        lambda *, deep=False: ready,
    )
    ready_doctor = collect_doctor()
    monkeypatch.setattr(
        effect_runtime,
        "collect_effect_runtime_readiness",
        lambda *, deep=False: missing,
    )
    missing_doctor = collect_doctor()

    assert ready_doctor["ok"] is True
    assert missing_doctor["ok"] is False
    runtime_check = next(
        check
        for check in missing_doctor["checks"]
        if check["id"] == "typescript_effect_runtime_ready"
    )
    assert runtime_check == {
        "id": "typescript_effect_runtime_ready",
        "required": True,
        "ok": False,
        "detail": "missing",
    }
    assert missing_doctor["typescript_control_plane"] == missing


def test_deep_doctor_fails_when_present_runtime_cannot_execute_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = {
        "schema_version": "loopx_effect_runtime_readiness_v0",
        "ready": False,
        "status": "probe_failed",
        "required_for": ["control_plane"],
        "default_cli_blocking": True,
        "minimum_node_version": "22.6.0",
        "detected_node_version": "24.1.0",
        "semantic_probe": "failed",
        "recommended_action": "Reinstall LoopX.",
    }
    monkeypatch.setattr(
        effect_runtime,
        "collect_effect_runtime_readiness",
        lambda *, deep=False: failed,
    )
    monkeypatch.setattr(
        "loopx.release_candidate.collect_release_candidate_checks",
        lambda **_kwargs: {"ok": True, "checks": []},
    )

    doctor = collect_doctor(deep=True)

    runtime_check = next(
        check
        for check in doctor["checks"]
        if check["id"] == "typescript_effect_runtime_ready"
    )
    assert runtime_check["required"] is True
    assert runtime_check["ok"] is False
    assert doctor["ok"] is False
