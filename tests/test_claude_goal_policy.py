from __future__ import annotations

import sys
from pathlib import Path

# goal_policy.py is a standalone hook script that imports its sibling modules by
# bare name (e.g. `from goal_state import active_context`), so load it via the
# hooks directory rather than the package namespace.
_HOOKS = Path(__file__).resolve().parents[1] / "loopx" / "claude_goal_mode" / "hooks"
sys.path.insert(0, str(_HOOKS))

import goal_policy  # noqa: E402

resolve_should_run = goal_policy.resolve_should_run


def test_resolve_should_run_prefers_policy_decision() -> None:
    # New architecture (on by default): the unified decision is authoritative.
    # A deny outcome over a permissive quota should_run must NOT run.
    assert resolve_should_run({"should_run": True, "policy_decision": {"outcome": "deny"}}) is False
    assert resolve_should_run({"should_run": True, "policy_decision": {"outcome": "wait"}}) is False
    assert resolve_should_run({"should_run": True, "policy_decision": {"outcome": "run"}}) is True
    # deny/wait over a non-running quota stays not-running.
    assert resolve_should_run({"should_run": False, "policy_decision": {"outcome": "deny"}}) is False


def test_resolve_should_run_falls_back_to_legacy_should_run() -> None:
    # No policy_decision (opt-out / legacy): the quota should_run bool decides.
    assert resolve_should_run({"should_run": True}) is True
    assert resolve_should_run({"should_run": False}) is False
    assert resolve_should_run({"should_run": "not-a-bool"}) is None
    assert resolve_should_run({}) is None


def test_resolve_should_run_ignores_malformed_policy_decision() -> None:
    # A malformed policy_decision falls back to the legacy should_run.
    assert resolve_should_run({"should_run": True, "policy_decision": "junk"}) is True
    assert resolve_should_run({"should_run": True, "policy_decision": {"outcome": "weird"}}) is True
    assert resolve_should_run({"should_run": False, "policy_decision": {}}) is False
