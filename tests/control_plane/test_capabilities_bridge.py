"""Tests for the capability-pack bridge (P1/P2/P3)."""

from __future__ import annotations

import pytest

from loopx.capabilities.catalog import build_capability_registry
from loopx.capabilities.registry import CapabilityRegistry
from loopx.control_plane.capabilities_bridge import (
    CapabilityEventHub,
    CapabilityHookRegistry,
    capability_pack_ready,
    capability_token,
    capability_token_set,
    discover_cli_registrars,
    eligible_bridged,
    register_all_capability_commands,
    resolve_required_tokens,
    split_binding_ref,
)


# ---------------------------------------------------------------------------
# Token normalization
# ---------------------------------------------------------------------------


def test_capability_token_normalizes_hyphens():
    assert capability_token("issue-fix") == "issue_fix"
    assert capability_token("Issue-Fix") == "issue_fix"
    assert capability_token("issue fix") == "issue_fix"
    assert capability_token(None) is None
    assert capability_token("") is None


def test_capability_token_set_accepts_various_shapes():
    assert capability_token_set("issue-fix, pull-request-review") == {
        "issue_fix",
        "pull_request_review",
    }
    assert capability_token_set(["issue-fix", "shell"]) == {"issue_fix", "shell"}
    assert capability_token_set(None) == set()


def test_split_binding_ref():
    assert split_binding_ref("issue-fix:feasibility_v0") == ("issue-fix", "feasibility_v0")
    assert split_binding_ref(None) is None
    assert split_binding_ref("not-a-valid-binding") is None


# ---------------------------------------------------------------------------
# P1: registry-driven eligibility
# ---------------------------------------------------------------------------


def _registry() -> CapabilityRegistry:
    return build_capability_registry()


def test_capability_pack_ready_for_builtin():
    registry = _registry()
    assert capability_pack_ready(registry, "issue-fix") is True
    assert capability_pack_ready(registry, "issue_fix") is True  # token form too


def test_capability_pack_ready_unknown_is_false():
    registry = _registry()
    assert capability_pack_ready(registry, "does-not-exist") is False


def test_eligible_bridged_plain_tokens_unchanged():
    # No binding, no registry -> original token matching.
    worker = {"capabilities": ["shell", "filesystem_read"]}
    assert eligible_bridged(worker, {"required_capabilities": ["shell"]}) is True
    assert eligible_bridged(worker, {"required_capabilities": ["network"]}) is False


def test_eligible_bridged_binding_requires_pack_token():
    worker = {"capabilities": ["issue_fix"]}
    task = {"capability_binding_ref": "issue-fix:feasibility_v0"}
    assert eligible_bridged(worker, task) is True
    assert eligible_bridged({"capabilities": ["shell"]}, task) is False


def test_eligible_bridged_binding_gated_by_registry_ready():
    registry = _registry()
    worker = {"capabilities": ["issue_fix"]}
    task = {"capability_binding_ref": "issue-fix:feasibility_v0"}
    assert eligible_bridged(worker, task, registry=registry) is True
    # Unknown pack binding fails closed even if worker declares a token.
    unknown_task = {"capability_binding_ref": "nope:xyz"}
    assert eligible_bridged(worker, unknown_task, registry=registry) is False


def test_resolve_required_tokens_merges_binding():
    task = {
        "required_capabilities": ["shell"],
        "capability_binding_ref": "issue-fix:feasibility_v0",
    }
    tokens = resolve_required_tokens(task)
    assert tokens == ["shell", "issue_fix"]


# ---------------------------------------------------------------------------
# P2: registry-driven CLI registration (real catalog)
# ---------------------------------------------------------------------------


def test_discover_cli_registrars_finds_real_packs():
    registry = _registry()
    records = registry.records(include_internal=False)
    registrars = discover_cli_registrars(records)
    # issue-fix and change-quality-qualification have CLIs whose module names
    # differ from their ids; the bridge must still find them.
    assert "issue-fix" in registrars
    assert "change-quality-qualification" in registrars
    assert "integration-branch-reconcile" in registrars


def test_discover_cli_registrars_is_tolerant():
    # Records that lack implemented_protocols or a CLI are simply skipped.
    registrars = discover_cli_registrars(
        [
            {"id": "no-such-pack", "implemented_protocols": []},
            {"id": "bare-pack"},
        ]
    )
    assert registrars == {}


class _FakeSubparsers:
    def __init__(self):
        self.registered: list[tuple] = []

    def add_parser(self, name, **kwargs):
        self.registered.append((name, kwargs))
        return _FakeParser()


class _FakeParser:
    def add_argument(self, *args, **kwargs):
        return None


def test_register_all_capability_commands_runs_registrars():
    # A synthetic pack with a single-arg registrar and one with the legacy
    # two-arg shape both register without error.
    calls: list[str] = []

    def single_arg_registrar(subparsers):
        calls.append("single")

    def two_arg_registrar(subparsers, add_format):
        calls.append("two")

    import types

    fake_module_a = types.SimpleNamespace(register_commands=single_arg_registrar)
    fake_module_b = types.SimpleNamespace(register_commands=two_arg_registrar)

    monkeypatch = pytest.MonkeyPatch()
    import importlib

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda p: fake_module_a if p.endswith(".a.cli") else fake_module_b,
    )
    try:
        registrars = register_all_capability_commands(
            _FakeSubparsers(),
            None,
            capability_records=[
                {"id": "pack-a", "implemented_protocols": [{"module": "loopx.capabilities.a.core"}]},
                {"id": "pack-b", "implemented_protocols": [{"module": "loopx.capabilities.b.core"}]},
            ],
        )
    finally:
        monkeypatch.undo()

    assert len(registrars) == 2
    assert set(calls) == {"single", "two"}


def test_register_all_capability_commands_internal_type_error_not_retried():
    # A two-arg registrar that raises TypeError *inside* its body must not be
    # re-invoked with a single argument (the old exception-probe fallback would
    # mask this kind of bug by calling the registrar a second time).
    calls: list[str] = []

    def flaky_two_arg(subparsers, add_format):
        calls.append("two")
        raise TypeError("internal boom")

    import types

    fake_module = types.SimpleNamespace(register_commands=flaky_two_arg)
    monkeypatch = pytest.MonkeyPatch()
    import importlib

    monkeypatch.setattr(importlib, "import_module", lambda p: fake_module)
    try:
        with pytest.raises(TypeError, match="internal boom"):
            register_all_capability_commands(
                _FakeSubparsers(),
                None,
                capability_records=[
                    {"id": "pack-flaky", "implemented_protocols": [{"module": "loopx.capabilities.flaky.core"}]},
                ],
            )
    finally:
        monkeypatch.undo()

    assert calls == ["two"]  # invoked exactly once, no fallback re-try


# ---------------------------------------------------------------------------
# P3: event hub + hook registry
# ---------------------------------------------------------------------------


def test_capability_event_hub_publish_and_subscribe():
    hub = CapabilityEventHub()
    received: list[dict] = []

    def on_pr_merge(event):
        received.append(dict(event))

    hub.subscribe("pr_merge", on_pr_merge, source="issue-fix")
    hub.publish("pr_merge", {"pr_ref": "owner/repo#1"})
    assert received == [{"pr_ref": "owner/repo#1"}]
    assert hub.kinds() == ["pr_merge"]


def test_capability_event_hub_isolates_failures():
    hub = CapabilityEventHub()

    def broken(event):
        raise RuntimeError("boom")

    def good(event):
        return {"ok": True}

    hub.subscribe("task_completed", broken, source="bad")
    hub.subscribe("task_completed", good, source="good")
    results, errors = hub.publish("task_completed", {})
    # Results and errors are returned separately so callers can tell a broken
    # subscriber apart from a legitimate result.
    assert results == [{"ok": True}]
    assert errors == [{"source": "bad", "error": "boom", "event_kind": "task_completed"}]


def test_capability_hook_registry_run_and_isolate():
    registry = CapabilityHookRegistry()
    calls: list[str] = []

    def hook_a(**kwargs):
        calls.append("a")
        return {"ok": True, "hook": "a"}

    def hook_b(**kwargs):
        raise RuntimeError("boom")

    registry.register("pre_quota", hook_a, source="pack-a")
    registry.register("pre_quota", hook_b, source="pack-b")
    results = registry.run("pre_quota", goal_id="g1")

    assert calls == ["a"]
    assert {"ok": True, "hook": "a"} in results
    assert any(r.get("ok") is False and "boom" in r.get("error", "") for r in results)
    assert registry.hook_points() == ["pre_quota"]
