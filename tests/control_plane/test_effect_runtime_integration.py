from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from loopx.control_plane import effect_runtime


def _journal(effect_id: str) -> dict[str, object]:
    return {
        "schema_version": "loopx_turn_journal_v0",
        "goal_id": "fixture-goal",
        "turn_key": "sha256:" + "a" * 64,
        "status": "in_progress",
        "completed_phases": ["host_execute"],
        "plan": {
            "transaction": {"settlement_plan": {"identity": {"effect_id": effect_id}}}
        },
    }


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def test_windows_pid_liveness_uses_a_non_signaling_probe(monkeypatch) -> None:
    calls: list[int] = []
    fake_os = SimpleNamespace(name="nt")

    def probe(pid: int) -> bool:
        calls.append(pid)
        return True

    monkeypatch.setattr(effect_runtime, "os", fake_os)
    monkeypatch.setattr(effect_runtime, "_windows_pid_is_alive", probe)

    assert effect_runtime._pid_is_alive(1234) is True
    assert calls == [1234]


def test_managed_runtime_is_reused_and_restart_safe_for_typed_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")

    first = effect_runtime.effect_runtime_result("runtime.ping", {})
    second = effect_runtime.effect_runtime_result("runtime.ping", {})
    assert first["pid"] == second["pid"]

    journal_path = tmp_path / "turn.json"
    effect_id = "goal:agent:todo:turn"
    payload = _journal(effect_id)
    committed = effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": payload,
            "expected_effect_id": effect_id,
            "expected_previous_sha256": None,
        },
    )
    assert committed["appended"] is True
    assert committed["replayed"] is False
    assert committed["effect_id"] == effect_id
    assert json.loads(journal_path.read_text(encoding="utf-8")) == payload

    effect_runtime.effect_runtime_result(
        "runtime.shutdown",
        {},
        retry_safe=False,
    )
    deadline = time.monotonic() + 2
    while list(runtime_dir.glob("runtime-*.json")) and time.monotonic() < deadline:
        time.sleep(0.025)

    replayed = effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": payload,
            "expected_effect_id": effect_id,
            "expected_previous_sha256": _digest(journal_path),
        },
    )
    assert replayed["appended"] is False
    assert replayed["replayed"] is True
    assert json.loads(journal_path.read_text(encoding="utf-8")) == payload

    effect_runtime.effect_runtime_result(
        "runtime.shutdown",
        {},
        retry_safe=False,
    )


def test_runtime_decode_change_rotates_identity_and_starts_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = Path(effect_runtime.__file__).resolve().parent
    staged_root = tmp_path / "control_plane"
    for relative in effect_runtime._runtime_source_files(source_root):
        source = source_root / relative
        target = staged_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_control_plane_root", lambda: staged_root)
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "250")

    original_fingerprint = effect_runtime._runtime_fingerprint()
    original = effect_runtime.effect_runtime_result("runtime.ping", {})
    decoder = staged_root / "runtime_decode.ts"
    decoder.write_bytes(decoder.read_bytes() + b"\n// decoder-fingerprint-probe\n")
    replacement_fingerprint = effect_runtime._runtime_fingerprint()
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})

    assert replacement_fingerprint != original_fingerprint
    assert int(replacement["pid"]) != int(original["pid"])
    original_info = effect_runtime._runtime_info_path(original_fingerprint)
    replacement_info = effect_runtime._runtime_info_path(replacement_fingerprint)
    assert original_info != replacement_info
    assert replacement_info.exists()

    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)
    deadline = time.monotonic() + 2
    while (
        original_info.exists() or replacement_info.exists()
    ) and time.monotonic() < deadline:
        time.sleep(0.025)
    assert not original_info.exists()
    assert not replacement_info.exists()


def test_typed_write_rejects_cross_effect_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    journal_path = tmp_path / "turn.json"
    first = _journal("effect-one")
    effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": first,
            "expected_effect_id": "effect-one",
            "expected_previous_sha256": None,
        },
    )

    try:
        effect_runtime.effect_runtime_result(
            "turn_journal.write",
            {
                "path": str(journal_path),
                "journal": _journal("effect-two"),
                "expected_effect_id": "effect-two",
                "expected_previous_sha256": _digest(journal_path),
            },
        )
    except RuntimeError as exc:
        assert "belongs to another settlement effect" in str(exc)
    else:
        raise AssertionError("cross-effect overwrite must fail closed")
    assert json.loads(journal_path.read_text(encoding="utf-8")) == first

    effect_runtime.effect_runtime_result(
        "runtime.shutdown",
        {},
        retry_safe=False,
    )


def test_typed_write_serializes_same_effect_checkpoints_with_cas(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    journal_path = tmp_path / "turn.json"
    effect_id = "goal:agent:todo:turn"
    initial = _journal(effect_id)
    effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": initial,
            "expected_effect_id": effect_id,
            "expected_previous_sha256": None,
        },
    )
    expected_previous_sha256 = _digest(journal_path)
    first = {**initial, "status": "committed"}
    second = {**initial, "status": "failed"}

    def commit(payload: dict[str, object]) -> dict[str, object] | RuntimeError:
        try:
            return effect_runtime.effect_runtime_result(
                "turn_journal.write",
                {
                    "path": str(journal_path),
                    "journal": payload,
                    "expected_effect_id": effect_id,
                    "expected_previous_sha256": expected_previous_sha256,
                },
            )
        except RuntimeError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(commit, (first, second)))

    assert sum(isinstance(outcome, RuntimeError) for outcome in outcomes) == 1
    failure = next(outcome for outcome in outcomes if isinstance(outcome, RuntimeError))
    assert "compare-and-swap precondition failed" in str(failure)
    assert json.loads(journal_path.read_text(encoding="utf-8")) in (first, second)
    success = next(outcome for outcome in outcomes if isinstance(outcome, dict))
    assert success["appended"] is True
    assert success["replayed"] is False

    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_successive_same_effect_checkpoints_receive_distinct_operation_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    journal_path = tmp_path / "turn.json"
    effect_id = "goal:agent:todo:turn"
    initial = _journal(effect_id)
    first = effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": initial,
            "expected_effect_id": effect_id,
            "expected_previous_sha256": None,
        },
    )
    successor = {**initial, "status": "committed"}
    second = effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": successor,
            "expected_effect_id": effect_id,
            "expected_previous_sha256": _digest(journal_path),
        },
    )

    assert first["operation_id"] != second["operation_id"]
    assert json.loads(journal_path.read_text(encoding="utf-8")) == successor
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_retry_safe_typed_write_recovers_after_unexpected_runtime_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")

    original = effect_runtime.effect_runtime_result("runtime.ping", {})
    original_pid = int(original["pid"])
    os.kill(original_pid, signal.SIGTERM)
    time.sleep(0.1)

    journal_path = tmp_path / "turn.json"
    effect_id = "goal:agent:todo:crash-recovery"
    payload = _journal(effect_id)
    committed = effect_runtime.effect_runtime_result(
        "turn_journal.write",
        {
            "path": str(journal_path),
            "journal": payload,
            "expected_effect_id": effect_id,
            "expected_previous_sha256": None,
        },
        retry_safe=True,
    )
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})

    assert committed["appended"] is True
    assert committed["replayed"] is False
    assert committed["effect_id"] == effect_id
    assert json.loads(journal_path.read_text(encoding="utf-8")) == payload
    assert replacement["pid"] != original_pid

    effect_runtime.effect_runtime_result(
        "runtime.shutdown",
        {},
        retry_safe=False,
    )


def test_dead_runtime_metadata_is_replaced_after_host_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    runtime_dir.mkdir()
    fingerprint = effect_runtime._runtime_fingerprint()
    info_path = effect_runtime._runtime_info_path(fingerprint)
    info_path.write_text(
        json.dumps(
            {
                "schema_version": effect_runtime.EFFECT_RUNTIME_INFO_SCHEMA_VERSION,
                "fingerprint": fingerprint,
                "pid": 99_999_999,
                "host": "127.0.0.1",
                "port": 9,
                "token": "stale-after-reboot",
            }
        ),
        encoding="utf-8",
    )

    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})

    assert replacement["ready"] is True
    assert int(replacement["pid"]) != 99_999_999
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_dead_startup_lock_is_reclaimed_without_waiting_for_age_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    runtime_dir.mkdir()
    fingerprint = effect_runtime._runtime_fingerprint()
    lock = runtime_dir / f"start-{fingerprint[:16]}.lock"
    lock.write_text("99999999\n", encoding="utf-8")

    started_at = time.monotonic()
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})

    assert replacement["ready"] is True
    assert time.monotonic() - started_at < 3
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_runtime_ready_budget_starts_after_start_lock_acquisition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    fingerprint = "f" * 64
    info_path = runtime_dir / "runtime.json"
    lock = runtime_dir / f"start-{fingerprint[:16]}.lock"
    lock.write_text(f"{os.getpid()}\n", encoding="utf-8")
    clock = {"monotonic": 0.0}
    ready_info = {
        "schema_version": effect_runtime.EFFECT_RUNTIME_INFO_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "pid": os.getpid(),
        "host": "127.0.0.1",
        "port": 1,
        "token": "fixture-token",
    }

    def sleep(seconds: float) -> None:
        clock["monotonic"] += seconds
        lock.unlink(missing_ok=True)

    def read_info(_path: Path, *, fingerprint: str):
        assert fingerprint == "f" * 64
        return ready_info if clock["monotonic"] >= 1.5 else None

    class _RunningProcess:
        def poll(self):
            return None

        def terminate(self) -> None:
            raise AssertionError("the runtime still has a fresh ready budget")

    monkeypatch.setattr(effect_runtime, "_read_info", read_info)
    monkeypatch.setattr(effect_runtime, "_node_executable", lambda: "node")
    monkeypatch.setattr(
        effect_runtime.subprocess,
        "Popen",
        lambda *_args, **_kwargs: _RunningProcess(),
    )
    monkeypatch.setattr(effect_runtime, "STARTUP_LOCK_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(effect_runtime, "STARTUP_READY_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(effect_runtime, "STARTUP_POLL_SECONDS", 0.75)
    monkeypatch.setattr(
        effect_runtime,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock["monotonic"],
            sleep=sleep,
            time=time.time,
        ),
    )

    assert effect_runtime._start_runtime(
        fingerprint=fingerprint,
        info_path=info_path,
    ) == ready_info
    assert clock["monotonic"] == 1.5


def test_early_runtime_exit_surfaces_stable_startup_diagnostic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setattr(effect_runtime, "_node_executable", lambda: "node")

    class _ExitedProcess:
        def poll(self) -> int:
            return 23

    launch: dict[str, object] = {}

    def popen(*_args, **kwargs):
        launch.update(kwargs)
        return _ExitedProcess()

    monkeypatch.setattr(
        effect_runtime.subprocess,
        "Popen",
        popen,
    )

    try:
        effect_runtime.effect_runtime_result("runtime.ping", {})
    except effect_runtime.EffectRuntimeStartupError as exc:
        assert exc.diagnostic_code == "runtime_exited_before_ready"
        assert "exit_code=23" in str(exc)
    else:
        raise AssertionError("an early runtime exit must fail with a stable diagnostic")
    assert launch["close_fds"] is True


def test_managed_runtime_releases_memory_after_idle_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "150")

    original = effect_runtime.effect_runtime_result("runtime.ping", {})
    original_pid = int(original["pid"])
    deadline = time.monotonic() + 2
    while list(runtime_dir.glob("runtime-*.json")) and time.monotonic() < deadline:
        time.sleep(0.025)

    assert list(runtime_dir.glob("runtime-*.json")) == []
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})
    assert int(replacement["pid"]) != original_pid

    effect_runtime.effect_runtime_result(
        "runtime.shutdown",
        {},
        retry_safe=False,
    )


def test_oversized_request_is_rejected_before_runtime_dispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")

    original = effect_runtime.effect_runtime_result("runtime.ping", {})
    original_pid = int(original["pid"])
    oversized = "x" * (effect_runtime.MAX_REQUEST_BYTES + 1)

    try:
        effect_runtime.effect_runtime_result(
            "effect.interpret_turn_result",
            {"packet": {"oversized": oversized}, "identity": {}},
        )
    except effect_runtime.EffectRuntimeRejected as exc:
        assert "request is oversized" in str(exc)
    else:
        raise AssertionError("oversized request must fail before dispatch")

    assert (
        effect_runtime.effect_runtime_result("runtime.ping", {})["pid"] == original_pid
    )
    effect_runtime.effect_runtime_result(
        "runtime.shutdown",
        {},
        retry_safe=False,
    )
