from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE_DIRECTORY = REPOSITORY / "examples" / "nokv-shadow-provider"
GUARD_PATH = EXAMPLE_DIRECTORY / "authority_guard.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_nokv_authority_guard",
        GUARD_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(EXAMPLE_DIRECTORY))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _selection_args(**values: object) -> SimpleNamespace:
    return SimpleNamespace(
        store_directory=values.get("store_directory"),
        nokv_client_config_json=values.get("nokv_client_config_json"),
        nokv_workbench=values.get("nokv_workbench"),
        goal_id="goal-a",
    )


def _base_cli() -> list[str]:
    return [
        "authority_guard.py",
        "--clock-file",
        "unused-clock",
        "--goal-id",
        "goal-a",
        "--agent-id",
        "agent-a",
        "--todo-id",
        "todo-a",
    ]


def _checkpoint() -> io.StringIO:
    return io.StringIO(
        json.dumps(
            {
                "goal_id": "goal-a",
                "agent_id": "agent-a",
                "todo_id": "todo-a",
                "checkpoint": "host_admission",
            }
        )
    )


def _run_main(
    guard: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    monkeypatch.setattr(guard.sys, "argv", argv)
    monkeypatch.setattr(guard.sys, "stdin", _checkpoint())
    monkeypatch.setattr(guard.sys, "stdout", stdout)
    return guard.main(), json.loads(stdout.getvalue())


def test_file_provider_remains_the_default_explicit_guard_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()

    def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("file selection must not construct a NoKV client")

    monkeypatch.setattr(guard, "build_client", unexpected, raising=False)
    monkeypatch.setattr(
        guard,
        "open_nokv_coordination_provider",
        unexpected,
        raising=False,
    )

    provider = guard._coordination_provider(
        _selection_args(store_directory=str(tmp_path))
    )

    assert isinstance(provider, guard.FileCoordinationProvider)
    assert provider.directory == tmp_path
    assert provider.goal_id == "goal-a"


def test_nokv_pair_uses_hardened_client_builder_and_typed_provider_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()
    monkeypatch.setenv("LOOPX_SHARED_AUTHORITY_TEST_ONLY", "1")
    config = {
        "root_id": "a" * 32,
        "routing": {
            "kind": "static",
            "endpoint": "127.0.0.1:7412",
            "logical_shard_id": "b" * 32,
            "object_namespace_id": "c" * 32,
            "placement_generation": 1,
            "owner_epoch": 1,
        },
        "object_store": {"kind": "memory"},
    }
    config_path = tmp_path / "nokv-client.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = object()
    built: list[object] = []
    factory_calls: list[tuple[object, str, str]] = []

    def build_client(value: object) -> object:
        built.append(value)
        return client

    provider_module = sys.modules[guard.open_nokv_coordination_provider.__module__]
    real_open = provider_module.open_nokv_coordination_provider

    def open_provider(client_factory: Any, workbench: str, goal_id: str) -> object:
        provider = real_open(client_factory, workbench, goal_id)
        factory_calls.append((provider, workbench, goal_id))
        return provider

    monkeypatch.setattr(guard, "build_client", build_client)
    monkeypatch.setattr(guard, "open_nokv_coordination_provider", open_provider)

    provider = guard._coordination_provider(
        _selection_args(
            nokv_client_config_json=str(config_path),
            nokv_workbench="authority-workbench",
        )
    )

    assert isinstance(provider, provider_module.NoKVCoordinationProvider)
    assert provider.client is client
    assert provider.workbench == "authority-workbench"
    assert provider.goal_id == "goal-a"
    assert built == [config]
    assert factory_calls == [(provider, "authority-workbench", "goal-a")]


def test_nokv_selection_requires_the_existing_test_only_environment_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()
    config_path = tmp_path / "nokv-client.json"
    config_path.write_text("{}", encoding="utf-8")
    client_constructions: list[object] = []

    def build_client(config: object) -> object:
        client_constructions.append(config)
        return object()

    monkeypatch.delenv("LOOPX_SHARED_AUTHORITY_TEST_ONLY", raising=False)
    monkeypatch.setattr(guard, "build_client", build_client)

    return_code, result = _run_main(
        guard,
        monkeypatch,
        [
            *_base_cli(),
            "--nokv-client-config-json",
            str(config_path),
            "--nokv-workbench",
            "authority-workbench",
        ],
    )

    assert return_code == 0
    assert result["reason_code"] == "authority_guard_unavailable"
    assert client_constructions == []


@pytest.mark.parametrize("invalid_path", ["relative-client.json", "/dev/null"])
def test_nokv_config_requires_an_absolute_regular_file(
    invalid_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()
    monkeypatch.setenv("LOOPX_SHARED_AUTHORITY_TEST_ONLY", "1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "relative-client.json").write_text("{}", encoding="utf-8")
    client_constructions: list[object] = []

    def build_client(config: object) -> object:
        client_constructions.append(config)
        return object()

    monkeypatch.setattr(guard, "build_client", build_client)

    return_code, result = _run_main(
        guard,
        monkeypatch,
        [
            *_base_cli(),
            "--nokv-client-config-json",
            invalid_path,
            "--nokv-workbench",
            "authority-workbench",
        ],
    )

    assert return_code == 0
    assert result["reason_code"] == "authority_guard_unavailable"
    assert client_constructions == []


def test_nokv_config_is_bounded_before_json_or_sdk_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()
    monkeypatch.setenv("LOOPX_SHARED_AUTHORITY_TEST_ONLY", "1")
    config_path = tmp_path / "oversized-client.json"
    config_path.write_text(
        json.dumps({"padding": "x" * (1 << 20)}),
        encoding="utf-8",
    )
    client_constructions: list[object] = []

    def build_client(config: object) -> object:
        client_constructions.append(config)
        return object()

    monkeypatch.setattr(guard, "build_client", build_client)

    return_code, result = _run_main(
        guard,
        monkeypatch,
        [
            *_base_cli(),
            "--nokv-client-config-json",
            str(config_path),
            "--nokv-workbench",
            "authority-workbench",
        ],
    )

    assert return_code == 0
    assert result["reason_code"] == "authority_guard_unavailable"
    assert client_constructions == []


@pytest.mark.parametrize(
    "backend_args",
    [
        [
            "--store-directory",
            "unused-file-store",
            "--nokv-client-config-json",
            "configuration-path-must-not-leak",
            "--nokv-workbench",
            "authority-workbench",
        ],
        ["--nokv-client-config-json", "configuration-path-must-not-leak"],
        ["--nokv-workbench", "authority-workbench"],
        [],
    ],
)
def test_backend_selection_conflicts_or_missing_pair_fail_closed(
    backend_args: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()

    return_code, result = _run_main(
        guard,
        monkeypatch,
        [*_base_cli(), *backend_args],
    )

    assert return_code == 0
    assert result == {
        "ok": False,
        "reason_code": "authority_guard_unavailable",
        "reason": "authority guard could not verify current state",
    }
    assert "configuration-path-must-not-leak" not in json.dumps(result)


def test_nokv_sdk_failure_is_sanitized_and_never_falls_back_to_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = _load_guard()
    monkeypatch.setenv("LOOPX_SHARED_AUTHORITY_TEST_ONLY", "1")
    secret = "credential-must-not-leak"
    config_path = tmp_path / "sensitive-config.json"
    config_path.write_text(
        json.dumps(
            {
                "root_id": "a" * 32,
                "routing": {
                    "kind": "etcd",
                    "endpoints": ["http://unavailable.invalid"],
                    "key_prefix": "/nokv/control",
                },
                "object_store": {
                    "kind": "s3",
                    "bucket": "qualification",
                    "secret_access_key": secret,
                },
            }
        ),
        encoding="utf-8",
    )

    def unavailable(config: object) -> object:
        assert isinstance(config, dict)
        raise RuntimeError(f"{secret} from {config_path}")

    def no_file_fallback(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("NoKV failure must not fall back to file authority")

    monkeypatch.setattr(guard, "build_client", unavailable, raising=False)
    monkeypatch.setattr(guard, "FileCoordinationProvider", no_file_fallback)

    return_code, result = _run_main(
        guard,
        monkeypatch,
        [
            *_base_cli(),
            "--nokv-client-config-json",
            str(config_path),
            "--nokv-workbench",
            "authority-workbench",
        ],
    )

    encoded = json.dumps(result)
    assert return_code == 0
    assert result == {
        "ok": False,
        "reason_code": "authority_guard_unavailable",
        "reason": "authority guard could not verify current state",
    }
    assert secret not in encoded
    assert str(config_path) not in encoded
