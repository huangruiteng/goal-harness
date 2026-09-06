"""Shared row vocabulary and CLI helpers for the shared-goal-authority ladder.

Every row runner returns a ``RowOutcome`` or raises ``RowAssertionError``; the
helpers here drive the product only through ``run_cli`` and never import a
LoopX writer, so a row cannot become a second authority over the goal state.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .authority_e2e_fixtures import GoalWorkspace, JsonObject, run_cli

AGENT_A = "agent-a"


AGENT_B = "agent-b"


PRIMARY_VISIBILITY_TIMEOUT_SECONDS = 15.0


COMMITTED_OBSERVATION_OUTCOMES = frozenset({"captured", "replayed", "ambiguous_reconciled"})


LOCAL_SHADOW_SUMMARY_ENABLED = {
    "enabled": True,
    "mode": "file_one_way",
    "status": "enabled",
}


DEFAULT_OFF_PARITY_FIELDS: tuple[str, ...] = (
    "ok",
    "added",
    "already_exists",
    "metadata_updated",
    "status_changed",
    "role",
    "status",
    "task_class",
    "action_kind",
    "continuation_policy",
)


MIGRATION_SEED_SCHEMA = "loopx_state_migration_shadow_seed_evidence_v0"


class RowAssertionError(AssertionError):
    """A row invariant failed; the message is written to be public-safe."""


@dataclass(frozen=True)
class RowContext:
    """Per-row scratch root and the environment the row may consult."""

    root: Path
    environ: Mapping[str, str]


@dataclass(frozen=True)
class RowOutcome:
    """What a row runner returns when it did not raise."""

    status: str
    reason_code: str | None
    evidence: JsonObject


def passed(**evidence: object) -> RowOutcome:
    return RowOutcome(status="pass", reason_code=None, evidence=dict(evidence))


def unverified(reason_code: str, **evidence: object) -> RowOutcome:
    return RowOutcome(status="unverified", reason_code=reason_code, evidence=dict(evidence))


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise RowAssertionError(message)


def sha256_hex(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def shadow_evidence(payload: Mapping[str, object], *, label: str) -> JsonObject:
    evidence = payload.get("authority_shadow")
    expect(isinstance(evidence, dict), f"{label} must carry authority_shadow evidence")
    assert isinstance(evidence, dict)
    return {str(key): value for key, value in evidence.items()}


def committed_observation(payload: Mapping[str, object], *, label: str) -> JsonObject:
    evidence = shadow_evidence(payload, label=label)
    expect(
        evidence.get("outcome") in COMMITTED_OBSERVATION_OUTCOMES,
        f"{label} observation outcome must be captured, replayed, or ambiguous_reconciled",
    )
    expect(
        evidence.get("primary_writeback_preserved") is True,
        f"{label} must preserve the primary writeback",
    )
    expect(
        evidence.get("provider_to_local_writes") is False,
        f"{label} must never write from provider to local state",
    )
    expect(
        evidence.get("candidate_read_for_decision") is False,
        f"{label} must never read the candidate for a decision",
    )
    return evidence


def add_todo(workspace: GoalWorkspace, text: str) -> JsonObject:
    return run_cli(
        workspace,
        "todo",
        "add",
        "--goal-id",
        workspace.goal_id,
        "--role",
        "agent",
        "--text",
        text,
        "--task-class",
        "advancement_task",
    )


def acquire_lease(
    workspace: GoalWorkspace,
    *,
    todo_id: str,
    owner: str,
    idempotency_key: str,
) -> JsonObject:
    return run_cli(
        workspace,
        "task-lease",
        "acquire",
        "--goal-id",
        workspace.goal_id,
        "--todo-id",
        todo_id,
        "--owner",
        owner,
        "--idempotency-key",
        idempotency_key,
        "--ttl-seconds",
        "120",
    )


def configure_shadow(workspace: GoalWorkspace, *flags: str) -> JsonObject:
    return run_cli(workspace, "configure-goal", "--goal-id", workspace.goal_id, *flags)


def lease_version(payload: Mapping[str, object], *, label: str) -> str:
    lease = payload.get("lease")
    expect(isinstance(lease, dict), f"{label} must return a lease record")
    assert isinstance(lease, dict)
    return str(int(lease["version"]))


__all__ = [
    "AGENT_A",
    "AGENT_B",
    "COMMITTED_OBSERVATION_OUTCOMES",
    "DEFAULT_OFF_PARITY_FIELDS",
    "LOCAL_SHADOW_SUMMARY_ENABLED",
    "MIGRATION_SEED_SCHEMA",
    "PRIMARY_VISIBILITY_TIMEOUT_SECONDS",
    "RowAssertionError",
    "RowContext",
    "RowOutcome",
    "acquire_lease",
    "add_todo",
    "committed_observation",
    "configure_shadow",
    "expect",
    "lease_version",
    "passed",
    "shadow_evidence",
    "sha256_hex",
    "unverified",
]
