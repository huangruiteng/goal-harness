from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from loopx.cli_commands import project_lifecycle_sinks


@pytest.mark.parametrize("status", ["not_applicable", "not_configured"])
def test_local_only_explore_projection_does_not_require_optional_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    calls: list[bool] = []

    def project(**kwargs: Any) -> dict[str, Any]:
        calls.append(bool(kwargs["execute"]))
        return {"ok": True, "status": status, "projection": {}}

    implementation = SimpleNamespace(sync_issue_fix_explore_on_material_change=project)
    monkeypatch.setattr(
        project_lifecycle_sinks,
        "import_module",
        lambda name: implementation,
    )
    monkeypatch.setattr(
        project_lifecycle_sinks,
        "resolve_runtime_root",
        lambda registry, runtime_root_arg: tmp_path,
    )
    monkeypatch.setattr(project_lifecycle_sinks, "load_registry", lambda path: {})

    def unexpected_activation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("local-only projection must not activate a sink provider")

    monkeypatch.setattr(
        project_lifecycle_sinks,
        "resolve_extension_activation",
        unexpected_activation,
    )

    sync = project_lifecycle_sinks.lark_explore_graph_syncer(
        None,
        registry_path=tmp_path / "registry.json",
    )
    result = sync(execute=True)

    assert result["status"] == status
    assert calls == [False]
    assert "extension_activation" not in result


def test_external_explore_projection_activates_provider_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def project(**kwargs: Any) -> dict[str, Any]:
        if kwargs["execute"]:
            events.append("write")
            return {"ok": True, "status": "synced", "projection": {}}
        events.append("preview")
        return {"ok": True, "status": "would_sync", "projection": {}}

    implementation = SimpleNamespace(sync_issue_fix_explore_on_material_change=project)
    provider = SimpleNamespace(
        LARK_EXTENSION_ID="loopx-lark",
        LARK_PROJECTION_SINK_PERMISSION="lark.projection_sink.use",
    )

    def import_fake(name: str) -> object:
        if name == "loopx.extensions.lark.presentation.explore_results":
            return implementation
        if name == "loopx.extensions.lark":
            return provider
        raise AssertionError(name)

    monkeypatch.setattr(project_lifecycle_sinks, "import_module", import_fake)
    monkeypatch.setattr(
        project_lifecycle_sinks,
        "resolve_runtime_root",
        lambda registry, runtime_root_arg: tmp_path,
    )
    monkeypatch.setattr(project_lifecycle_sinks, "load_registry", lambda path: {})

    def activate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append("activate")
        return {"status": "active"}

    monkeypatch.setattr(
        project_lifecycle_sinks,
        "resolve_extension_activation",
        activate,
    )

    sync = project_lifecycle_sinks.lark_explore_graph_syncer(
        None,
        registry_path=tmp_path / "registry.json",
    )
    result = sync(execute=True)

    assert result["status"] == "synced"
    assert result["extension_activation"] == {"status": "active"}
    assert events == ["preview", "activate", "write"]
