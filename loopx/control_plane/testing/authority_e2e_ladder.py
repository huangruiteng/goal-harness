"""Incremental end-to-end stage ladder for the shared-goal-authority RFC.

One ladder, one row per completed RFC stage claim, one exit policy: the run
is green only when every selected row passed. A row that cannot run in this
environment (no PostgreSQL, no NoKV stack, no POSIX signals) reports
``unverified`` and, unless ``--allow-unverified`` is given, the ladder exits
non-zero. Rows for stages that later PRs will land are declared as
``pending`` so the report never silently claims them.

Rows drive the product through ``python -m loopx.cli`` (``real_cli``) or run
the retained store-level probes (``store_direct``); this module adds no
product path of its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from .authority_e2e_fixtures import (
    REPO_ROOT,
    TS_READBACK_PROBE,
    GoalWorkspace,
    JsonObject,
    LegacyMigrationSource,
    build_goal_workspace,
    build_legacy_migration_source,
    candidate_document,
    candidate_store_paths,
    hold_observation_lock,
    kill_now,
    node_executable,
    parse_json_object,
    run_cli,
    spawn_cli,
    tap_summary,
    ts_readback,
    unique_goal_id,
    wait_until,
)

REPORT_SCHEMA = "loopx_shared_goal_authority_e2e_report_v0"
LIST_SCHEMA = "loopx_shared_goal_authority_e2e_rows_v0"
STAGES: tuple[str, ...] = ("0", "1", "2a", "2b", "2c1", "2c2")
PRODUCT_PATHS: tuple[str, ...] = ("real_cli", "store_direct")
GATES: tuple[str, ...] = ("deterministic", "env:postgresql", "env:nokv", "env:nokv_legacy")
ROW_STATUSES: tuple[str, ...] = ("pass", "fail", "unverified")
EXIT_POLICY_RULE = "exit 0 iff fail == 0 and (unverified == 0 or allow_unverified)"

POSTGRES_URL_VARIABLE = "LOOPX_TEST_POSTGRES_URL"
NOKV_LIVE_FLAG = "NOKV_COORDINATION_LIVE"
NOKV_STACK_VARIABLES: tuple[str, ...] = (
    "NOKV_ETCD",
    "NOKV_ETCD_PREFIX",
    "NOKV_ROOT_ID",
    "NOKV_BUCKET",
    "NOKV_OBJECT_ENDPOINT",
    "NOKV_OBJECT_ROOT",
    "NOKV_OBJECT_KEY",
    "NOKV_OBJECT_SECRET",
)
NOKV_SECRET_VARIABLES: tuple[str, ...] = ("NOKV_OBJECT_KEY", "NOKV_OBJECT_SECRET")
GATE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "deterministic": (),
    "env:postgresql": (POSTGRES_URL_VARIABLE,),
    "env:nokv": (NOKV_LIVE_FLAG, *NOKV_STACK_VARIABLES),
    "env:nokv_legacy": (NOKV_LIVE_FLAG, *NOKV_STACK_VARIABLES),
}
GATE_UNVERIFIED_REASON: dict[str, str] = {
    "env:postgresql": "postgres_url_missing",
    "env:nokv": "nokv_live_env_missing",
    "env:nokv_legacy": "nokv_live_env_missing",
}

LIVE_E2E_SCRIPT = Path("examples") / "nokv-shadow-provider" / "live_e2e.py"
PG_INTEGRATION_TEST = (
    Path("tests") / "control_plane_ts" / "postgresql_authority_store.integration.test.ts"
)
PROBE_SOURCES: tuple[Path, ...] = (
    LIVE_E2E_SCRIPT,
    TS_READBACK_PROBE,
    PG_INTEGRATION_TEST,
    Path("loopx") / "control_plane" / "testing" / "authority_e2e_ladder.py",
    Path("loopx") / "control_plane" / "testing" / "authority_e2e_fixtures.py",
)
FILE_MATRIX_ROWS: tuple[str, ...] = (
    "same_todo_one_winner",
    "independent_todo_applies",
    "replay_returns_original_receipt",
    "identity_mismatch_rejected",
    "stale_revision_conflicts",
    "lost_response_recovers_receipt",
    "receipts_retained",
    "authority_revision_advanced_twice",
    "renew_extends_the_active_lease",
    "expired_lease_reclaimed_with_new_epoch",
    "superseded_executor_cannot_write_back",
    "complete_creates_claimable_successor_atomically",
)
NOKV_ONLY_MATRIX_ROW = "restored_lineage_fails_closed"
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
MINIMUM_POSTGRES_TAP_PASSES = 9
AGENT_A = "agent-a"
AGENT_B = "agent-b"
PRIMARY_VISIBILITY_TIMEOUT_SECONDS = 15.0


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


@dataclass(frozen=True)
class LadderRow:
    id: str
    stage: str
    title: str
    product_path: str
    gate: str
    posix_only: bool
    run: Callable[[RowContext], RowOutcome]

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"row {self.id}: unsupported stage {self.stage!r}")
        if self.product_path not in PRODUCT_PATHS:
            raise ValueError(f"row {self.id}: unsupported product_path {self.product_path!r}")
        if self.gate not in GATES:
            raise ValueError(f"row {self.id}: unsupported gate {self.gate!r}")

    def describe(self) -> JsonObject:
        return {
            "id": self.id,
            "stage": self.stage,
            "title": self.title,
            "product_path": self.product_path,
            "gate": self.gate,
            "posix_only": self.posix_only,
        }


@dataclass(frozen=True)
class PendingRow:
    id: str
    stage: str
    pending_until: str

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"pending row {self.id}: unsupported stage {self.stage!r}")

    def describe(self) -> JsonObject:
        return {
            "id": self.id,
            "stage": self.stage,
            "status": "pending",
            "pending_until": self.pending_until,
        }


@dataclass(frozen=True)
class RowResult:
    row: LadderRow
    status: str
    reason_code: str | None
    evidence: JsonObject
    duration_ms: int

    def as_dict(self) -> JsonObject:
        return {
            **self.row.describe(),
            "status": self.status,
            "reason_code": self.reason_code,
            "evidence": dict(self.evidence),
            "duration_ms": self.duration_ms,
        }


def passed(**evidence: object) -> RowOutcome:
    return RowOutcome(status="pass", reason_code=None, evidence=dict(evidence))


def unverified(reason_code: str, **evidence: object) -> RowOutcome:
    return RowOutcome(status="unverified", reason_code=reason_code, evidence=dict(evidence))


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise RowAssertionError(message)


def _sha256_hex(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _shadow_evidence(payload: Mapping[str, object], *, label: str) -> JsonObject:
    evidence = payload.get("authority_shadow")
    _expect(isinstance(evidence, dict), f"{label} must carry authority_shadow evidence")
    assert isinstance(evidence, dict)
    return {str(key): value for key, value in evidence.items()}


def _committed_observation(payload: Mapping[str, object], *, label: str) -> JsonObject:
    evidence = _shadow_evidence(payload, label=label)
    _expect(
        evidence.get("outcome") in COMMITTED_OBSERVATION_OUTCOMES,
        f"{label} observation outcome must be captured, replayed, or ambiguous_reconciled",
    )
    _expect(
        evidence.get("primary_writeback_preserved") is True,
        f"{label} must preserve the primary writeback",
    )
    _expect(
        evidence.get("provider_to_local_writes") is False,
        f"{label} must never write from provider to local state",
    )
    _expect(
        evidence.get("candidate_read_for_decision") is False,
        f"{label} must never read the candidate for a decision",
    )
    return evidence


def _add_todo(workspace: GoalWorkspace, text: str) -> JsonObject:
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


def _acquire_lease(
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


def _configure_shadow(workspace: GoalWorkspace, *flags: str) -> JsonObject:
    return run_cli(workspace, "configure-goal", "--goal-id", workspace.goal_id, *flags)


def _lease_version(payload: Mapping[str, object], *, label: str) -> str:
    lease = payload.get("lease")
    _expect(isinstance(lease, dict), f"{label} must return a lease record")
    assert isinstance(lease, dict)
    return str(int(lease["version"]))


def _run_live_matrix_script(environ: Mapping[str, str], *, live: bool) -> JsonObject:
    env = dict(environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    if not live:
        env.pop(NOKV_LIVE_FLAG, None)
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / LIVE_E2E_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    matrix = parse_json_object(completed.stdout)
    matrix["_exit_code"] = completed.returncode
    return matrix


def _matrix_rows(matrix: Mapping[str, object], key: str) -> dict[str, object]:
    rows = matrix.get(key)
    _expect(isinstance(rows, dict), f"live matrix must report {key}")
    assert isinstance(rows, dict)
    return {str(name): value for name, value in rows.items()}


def _false_rows(rows: Mapping[str, object]) -> list[str]:
    return sorted(name for name, value in rows.items() if value is not True)


# ---------------------------------------------------------------------------
# Stage 0: recoverable reference foundation (store_direct)
# ---------------------------------------------------------------------------


def _row_file_matrix_twelve_rows(context: RowContext) -> RowOutcome:
    matrix = _run_live_matrix_script(context.environ, live=False)
    file_rows = _matrix_rows(matrix, "file_provider")
    _expect(
        set(file_rows) == set(FILE_MATRIX_ROWS),
        "file provider matrix must contain exactly the twelve known rows",
    )
    _expect(not _false_rows(file_rows), "every file provider matrix row must be true")
    _expect(matrix["_exit_code"] == 0, "live matrix script must exit 0 without a stack")
    return passed(matrix_rows=len(file_rows), script_exit_code=matrix["_exit_code"])


def _row_nokv_live_matrix(context: RowContext) -> RowOutcome:
    matrix = _run_live_matrix_script(context.environ, live=True)
    nokv_rows = _matrix_rows(matrix, "nokv_provider")
    if "unverified" in nokv_rows:
        reason = str(nokv_rows["unverified"])
        code = "nokv_sdk_missing" if "SDK" in reason else "nokv_matrix_unverified"
        return unverified(code)
    expected = {*FILE_MATRIX_ROWS, NOKV_ONLY_MATRIX_ROW}
    _expect(set(nokv_rows) == expected, "NoKV matrix must contain the shared rows plus the lineage row")
    _expect(not _false_rows(nokv_rows), "every NoKV matrix row must be true")
    parity = _matrix_rows(matrix, "file_nokv_parity")
    _expect(parity.get("identical_row_outcomes") is True, "file and NoKV rows must be identical")
    _expect(parity.get("rows") == len(FILE_MATRIX_ROWS), "parity must cover the twelve shared rows")
    _expect(matrix["_exit_code"] == 0, "live matrix script must exit 0")
    return passed(
        nokv_rows=len(nokv_rows),
        parity_rows=parity.get("rows"),
        restored_lineage_fails_closed=True,
        script_exit_code=matrix["_exit_code"],
    )


# ---------------------------------------------------------------------------
# Stage 1: provider-neutral boundary, read back through the TypeScript store
# ---------------------------------------------------------------------------


def _row_cli_document_decodes_through_ts_store(context: RowContext) -> RowOutcome:
    if node_executable() is None:
        return unverified("node_missing")
    workspace = build_goal_workspace(
        context.root,
        goal_id=unique_goal_id("ladder-s1"),
        handoff_mode="hard_lease",
        shadow_enabled=True,
        runtime_root_binding="registry",
    )
    added = _add_todo(workspace, "Decode this observation through the TypeScript store.")
    todo_id = str(added["todo_id"])
    acquired = _acquire_lease(
        workspace,
        todo_id=todo_id,
        owner=AGENT_A,
        idempotency_key="ladder-s1-lease",
    )
    updated = run_cli(
        workspace,
        "todo",
        "update",
        "--goal-id",
        workspace.goal_id,
        "--todo-id",
        todo_id,
        "--note",
        "A public-safe note recorded after the lease.",
        "--agent-id",
        AGENT_A,
    )
    observations = [
        _committed_observation(payload, label=label)
        for label, payload in (("todo add", added), ("task-lease acquire", acquired), ("todo update", updated))
    ]
    _expect(
        all(evidence["outcome"] == "captured" for evidence in observations),
        "three distinct CLI writes must each be captured",
    )
    observation_ids = [str(evidence["observation_id"]) for evidence in observations]
    probe = ts_readback(workspace, receipt=observation_ids[0])
    _expect(probe is not None, "read-back probe requires node")
    assert probe is not None
    load = probe.get("load")
    scan = probe.get("scan")
    receipt = probe.get("receipt")
    _expect(isinstance(load, dict) and load.get("status") == "loaded", "TS store must load the CLI document")
    _expect(isinstance(load, dict) and load.get("cursor") == "3", "TS store cursor must be 3 after three writes")
    _expect(
        isinstance(load, dict)
        and load.get("provider_revision") == observations[-1]["provider_revision"],
        "TS store head revision must equal the last observation revision",
    )
    _expect(
        isinstance(scan, dict) and scan.get("operation_ids") == observation_ids,
        "scanCommitted must page through the three observation ids in order",
    )
    _expect(isinstance(receipt, dict) and receipt.get("status") == "found", "readReceipt must find the first observation")
    document = candidate_document(workspace)
    _expect(document.cursor == "3" and document.operation_ids == observation_ids, "candidate bytes must match the probe")
    assert isinstance(scan, dict)
    return passed(cursor="3", scan_pages=scan.get("pages"), observation_count=len(observation_ids))


# ---------------------------------------------------------------------------
# Stage 2B: PostgreSQL candidate conformance against a live database
# ---------------------------------------------------------------------------


def _pg_package_version() -> str | None:
    manifest = REPO_ROOT / "node_modules" / "pg" / "package.json"
    if not manifest.exists():
        return None
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return str(version) if version else None


def _row_postgresql_conformance_live(context: RowContext) -> RowOutcome:
    node = node_executable()
    if node is None:
        return unverified("node_missing")
    pg_version = _pg_package_version()
    if pg_version is None:
        return unverified("pg_dependency_missing")
    summary = tap_summary(
        [
            node,
            "--no-warnings",
            "--experimental-strip-types",
            "--test",
            "--test-reporter=tap",
            str(PG_INTEGRATION_TEST),
        ],
        env=context.environ,
        timeout=900,
    )
    _expect(summary.failed == 0, "PostgreSQL conformance must report zero TAP failures")
    _expect(summary.skipped == 0, "PostgreSQL conformance must not skip; the URL was not honoured")
    _expect(
        summary.passed is not None and summary.passed >= MINIMUM_POSTGRES_TAP_PASSES,
        "PostgreSQL conformance must pass the conformance suite plus provider tests",
    )
    _expect(summary.returncode == 0, "node test runner must exit 0")
    return passed(
        tap_pass=summary.passed,
        tap_fail=summary.failed,
        tap_skipped=summary.skipped,
        postgres_url_sha256_prefix=_sha256_hex(context.environ.get(POSTGRES_URL_VARIABLE, ""))[:12],
        pg_package_version=pg_version,
    )


# ---------------------------------------------------------------------------
# Stage 2C1: local post-commit observation through the product CLI
# ---------------------------------------------------------------------------


def _shadow_workspace(context: RowContext, prefix: str, *, shadow_enabled: bool) -> GoalWorkspace:
    return build_goal_workspace(
        context.root,
        goal_id=unique_goal_id(prefix),
        handoff_mode="hard_lease",
        shadow_enabled=shadow_enabled,
        runtime_root_binding="cli_override",
    )


def _row_configure_enable_disable_roundtrip(context: RowContext) -> RowOutcome:
    workspace = _shadow_workspace(context, "ladder-configure", shadow_enabled=False)
    preview = _configure_shadow(workspace, "--local-authority-shadow-file")
    _expect(preview.get("dry_run") is True and preview.get("written") is False, "preview must not write")
    enabled = _configure_shadow(workspace, "--local-authority-shadow-file", "--execute")
    _expect(enabled.get("written") is True, "enable must write the registry")

    observed = _add_todo(workspace, "Capture one post-commit observation through the product CLI.")
    evidence = _committed_observation(observed, label="todo add")
    _expect(evidence["outcome"] == "captured", "first observation must be captured")
    _expect(evidence["parity_verdict"] == "not_evaluated", "observation must not claim parity")
    lease = _acquire_lease(
        workspace,
        todo_id=str(observed["todo_id"]),
        owner=AGENT_A,
        idempotency_key="ladder-configure-lease",
    )
    _expect(lease.get("acquired") is True, "lease must be acquired")
    _expect(_committed_observation(lease, label="task-lease acquire")["outcome"] == "captured", "lease observation must be captured")
    document = candidate_document(workspace)
    _expect(len(document.todo_ids) == 1 and len(document.leases) == 1, "candidate head must hold one todo and one lease")

    inspected = _configure_shadow(workspace)
    after = inspected.get("after")
    _expect(
        isinstance(after, dict) and after.get("local_authority_shadow") == LOCAL_SHADOW_SUMMARY_ENABLED,
        "configure-goal must read back the enabled shadow summary",
    )
    disabled = _configure_shadow(workspace, "--clear-local-authority-shadow", "--execute")
    _expect(disabled.get("written") is True, "disable must write the registry")
    before_disabled_write = document.path.read_bytes()
    after_disable = _add_todo(workspace, "This local lifecycle write must not execute the observer.")
    _expect(after_disable.get("ok") is True and after_disable.get("added") is True, "disabled write must still commit")
    _expect("authority_shadow" not in after_disable, "disabled write must not observe")
    _expect(document.path.read_bytes() == before_disabled_write, "candidate bytes must not change once disabled")
    return passed(candidate_cursor=document.cursor, head_todos=1, head_leases=1)


def _row_default_off_isolation(context: RowContext) -> RowOutcome:
    enabled = _shadow_workspace(context, "ladder-enabled", shadow_enabled=True)
    baseline = _shadow_workspace(context, "ladder-baseline", shadow_enabled=False)
    text = "Capture one post-commit observation through the product CLI."
    observed = _add_todo(enabled, text)
    _committed_observation(observed, label="enabled todo add")
    default_off = _add_todo(baseline, text)
    _expect("authority_shadow" not in default_off, "default-off write must not carry observation evidence")
    differing = [field for field in DEFAULT_OFF_PARITY_FIELDS if observed.get(field) != default_off.get(field)]
    _expect(not differing, f"default-off response fields must match the observed response: {differing}")
    _expect(not (baseline.runtime_root / "authority-shadow").exists(), "default-off must not create candidate storage")
    return passed(compared_fields=len(DEFAULT_OFF_PARITY_FIELDS))


def _row_candidate_failure_preserves_primary(context: RowContext) -> RowOutcome:
    workspace = _shadow_workspace(context, "ladder-failure", shadow_enabled=False)
    _configure_shadow(workspace, "--local-authority-shadow-file", "--execute")
    workspace.runtime_root.mkdir(parents=True, exist_ok=True)
    (workspace.runtime_root / "authority-shadow").write_text("block candidate directory", encoding="utf-8")
    result = _add_todo(workspace, "The primary write survives a candidate construction failure.")
    _expect(result.get("ok") is True and result.get("added") is True, "primary write must commit")
    evidence = _shadow_evidence(result, label="todo add")
    _expect(evidence.get("outcome") == "failed", "candidate failure must be reported as failed")
    _expect(evidence.get("reason_code") == "shadow_observation_failed", "candidate failure must carry its typed reason")
    _expect(evidence.get("primary_writeback_preserved") is True, "candidate failure must preserve the primary writeback")
    _expect(
        str(result["todo_id"]) in workspace.state_path.read_text(encoding="utf-8"),
        "the committed todo must be present in the primary state",
    )
    return passed(outcome="failed", reason_code="shadow_observation_failed")


def _row_crash_gap_loses_observation(context: RowContext) -> RowOutcome:
    workspace = _shadow_workspace(context, "ladder-crash-gap", shadow_enabled=False)
    _configure_shadow(workspace, "--local-authority-shadow-file", "--execute")
    first_text = "Primary commit that loses its post-commit observation."
    with hold_observation_lock(workspace):
        process = spawn_cli(
            workspace,
            "todo",
            "add",
            "--goal-id",
            workspace.goal_id,
            "--role",
            "agent",
            "--text",
            first_text,
            "--task-class",
            "advancement_task",
        )
        try:
            visible = wait_until(
                lambda: first_text in workspace.state_path.read_text(encoding="utf-8"),
                PRIMARY_VISIBILITY_TIMEOUT_SECONDS,
            )
            _expect(visible, "primary Todo commit did not become visible")
            _expect(process.poll() is None, "writer must still be blocked on the observation lock")
        finally:
            kill_now(process)
    _expect(not candidate_store_paths(workspace), "a killed writer must leave no candidate document")
    recovered = _add_todo(workspace, "A later primary commit refreshes the current full snapshot.")
    evidence = _committed_observation(recovered, label="recovering todo add")
    _expect(evidence["outcome"] == "captured", "recovery observation must be captured")
    _expect(evidence["durable_source_outbox"] is False, "no durable outbox may be claimed")
    _expect(evidence["source_transaction_correlated"] is False, "no transaction correlation may be claimed")
    _expect(evidence["parity_verdict"] == "not_evaluated", "recovery must not claim parity")
    document = candidate_document(workspace)
    _expect(len(document.todo_ids) == 2, "the refreshed snapshot must include both primary commits")
    return passed(lost_observations=1, refreshed_head_todos=2, candidate_cursor=document.cursor)


@dataclass
class _WriterSequence:
    workspace: GoalWorkspace
    committed: list[tuple[str, JsonObject]] = field(default_factory=list)

    def commit(self, label: str, payload: JsonObject, *, flag: str) -> JsonObject:
        _expect(payload.get(flag) is True, f"{label} must report {flag}=true")
        self.committed.append((label, payload))
        return payload

    def cli(self, *args: str) -> JsonObject:
        return run_cli(self.workspace, *args, "--goal-id", self.workspace.goal_id)


def _writer_sequence_lease_lifecycle(sequence: _WriterSequence) -> str:
    """Add a todo, then acquire, update, renew, transfer, and complete it."""

    first = sequence.commit(
        "todo add",
        _add_todo(sequence.workspace, "Deliver one bounded control-plane change."),
        flag="added",
    )
    todo_id = str(first["todo_id"])
    acquired = sequence.commit(
        "task-lease acquire",
        _acquire_lease(sequence.workspace, todo_id=todo_id, owner=AGENT_A, idempotency_key="ladder-lease-a"),
        flag="acquired",
    )
    sequence.commit(
        "todo update",
        sequence.cli("todo", "update", "--todo-id", todo_id, "--note", "A public-safe update.", "--agent-id", AGENT_A),
        flag="changed",
    )
    renewed = sequence.commit(
        "task-lease renew",
        sequence.cli(
            "task-lease", "renew", "--todo-id", todo_id, "--owner", AGENT_A,
            "--idempotency-key", "ladder-lease-a",
            "--expected-version", _lease_version(acquired, label="acquire"),
            "--ttl-seconds", "120",
        ),
        flag="renewed",
    )
    transferred = sequence.commit(
        "task-lease transfer",
        sequence.cli(
            "task-lease", "transfer", "--todo-id", todo_id, "--owner", AGENT_A,
            "--idempotency-key", "ladder-lease-a", "--new-owner", AGENT_B,
            "--new-idempotency-key", "ladder-lease-b",
            "--expected-version", _lease_version(renewed, label="renew"),
            "--ttl-seconds", "120",
        ),
        flag="transferred",
    )
    sequence.commit(
        "todo complete",
        sequence.cli(
            "todo", "complete", "--todo-id", todo_id, "--agent-id", AGENT_B,
            "--task-lease-idempotency-key", "ladder-lease-b",
            "--task-lease-expected-version", _lease_version(transferred, label="transfer"),
            "--evidence", "validation://ladder-complete", "--no-follow-up",
        ),
        flag="completed",
    )
    return todo_id


def _writer_sequence_supersede_and_hygiene(sequence: _WriterSequence) -> str:
    """Add a second todo, replay its acquire, supersede it, then run hygiene writers."""

    second = sequence.commit(
        "todo add (second)",
        _add_todo(sequence.workspace, "Replace this bounded work with a successor."),
        flag="added",
    )
    todo_id = str(second["todo_id"])
    acquired = sequence.commit(
        "task-lease acquire (second)",
        _acquire_lease(sequence.workspace, todo_id=todo_id, owner=AGENT_A, idempotency_key="ladder-lease-c"),
        flag="acquired",
    )
    replayed = _acquire_lease(sequence.workspace, todo_id=todo_id, owner=AGENT_A, idempotency_key="ladder-lease-c")
    _expect(replayed.get("idempotent") is True, "re-acquire with the same key must be idempotent")
    _expect("authority_shadow" not in replayed, "an idempotent re-acquire must not observe")
    sequence.commit(
        "todo supersede",
        sequence.cli(
            "todo", "supersede", "--todo-id", todo_id, "--agent-id", AGENT_A,
            "--reason", "Replace obsolete work.",
            "--next-agent-todo", "Carry the bounded work forward.",
            "--task-lease-idempotency-key", "ladder-lease-c",
            "--task-lease-expected-version", _lease_version(acquired, label="acquire (second)"),
        ),
        flag="superseded",
    )
    sequence.commit(
        "todo capture-followups",
        sequence.cli(
            "todo", "capture-followups",
            "--follow-up", "Verify the migrated authority projection.",
            "--evidence", "validation://ladder-followup",
        ),
        flag="changed",
    )
    sequence.commit(
        "todo archive-completed",
        sequence.cli("todo", "archive-completed", "--max-active-done", "0", "--execute"),
        flag="changed",
    )
    return todo_id


def _row_every_writer_family_captures(context: RowContext) -> RowOutcome:
    workspace = build_goal_workspace(
        context.root,
        goal_id=unique_goal_id("ladder-writers"),
        handoff_mode="legacy",
        shadow_enabled=True,
        runtime_root_binding="cli_override",
    )
    sequence = _WriterSequence(workspace)
    sequence.commit(
        "handoff-mode set",
        sequence.cli("handoff-mode", "set", "--mode", "hard_lease"),
        flag="changed",
    )
    first_todo = _writer_sequence_lease_lifecycle(sequence)
    second_todo = _writer_sequence_supersede_and_hygiene(sequence)

    observations = [_committed_observation(payload, label=label) for label, payload in sequence.committed]
    captured = [evidence for evidence in observations if evidence["outcome"] == "captured"]
    document = candidate_document(workspace)
    _expect(document.cursor == str(len(captured)), "candidate cursor must equal the number of captured observations")
    _expect(
        set(document.operation_ids) == {str(evidence["observation_id"]) for evidence in observations},
        "candidate operation ids must be exactly the observation ids",
    )
    _expect(
        {str(lease.get("todo_id")) for lease in document.leases} == {first_todo, second_todo},
        "candidate head must retain the lease records of both leased todos",
    )
    _expect(
        all(lease.get("status") == "released" for lease in document.leases),
        "no time-active lease may remain in the candidate head",
    )
    listed = sequence.cli("todo", "list")
    listed_ids = sorted(str(todo.get("todo_id")) for todo in listed.get("todos") or [] if isinstance(todo, dict))
    _expect(sorted(document.todo_ids) == listed_ids, "candidate head todos must equal the projected todo list")
    return passed(
        writer_families=len(sequence.committed),
        captured=len(captured),
        outcomes=sorted({str(evidence["outcome"]) for evidence in observations}),
        candidate_cursor=document.cursor,
        head_todos=len(document.todo_ids),
        head_leases=len(document.leases),
    )


def _migration_arguments(source: LegacyMigrationSource) -> list[str]:
    return [
        "migrate-state",
        "--legacy-registry", str(source.legacy_registry),
        "--legacy-runtime-root", str(source.legacy_runtime),
        "--target-runtime-root", str(source.target_runtime),
        "--goal-id", source.old_goal_id,
        "--goal-id-map", f"{source.old_goal_id}={source.new_goal_id}",
        "--path-map", f"{source.source_repo}={source.target_repo}",
        "--copy-active-state",
        "--copy-runtime",
        "--no-global-sync",
    ]


def _first_entry(payload: Mapping[str, object], key: str, *, label: str) -> JsonObject:
    entries = payload.get(key)
    _expect(isinstance(entries, list) and len(entries) == 1, f"{label} must report exactly one {key} entry")
    assert isinstance(entries, list)
    entry = entries[0]
    _expect(isinstance(entry, dict), f"{label} {key} entry must be an object")
    assert isinstance(entry, dict)
    return {str(field): value for field, value in entry.items()}


def _assert_migration_preview(source: LegacyMigrationSource, preview: JsonObject, sentinel: bytes) -> None:
    _expect(preview.get("ok") is True and preview.get("dry_run") is True, "migration preview must be a dry run")
    _expect(source.target_registry.read_bytes() == sentinel, "dry run must not write the target registry")
    _expect(not source.target_runtime.exists(), "dry run must not create the target runtime")
    runtime_result = _first_entry(preview, "runtime_goals", label="migration preview")
    _expect(runtime_result.get("copied_file_count") == 0, "dry run must copy no runtime files")
    seed = _first_entry(preview, "authority_shadow_seeds", label="migration preview")
    _expect(
        seed
        == {
            "schema_version": MIGRATION_SEED_SCHEMA,
            "goal_id": source.new_goal_id,
            "attempted": False,
            "outcome": "planned",
            "reason_code": None,
        },
        "dry run must plan, not attempt, the shadow seed",
    )
    _expect(source.private_marker not in json.dumps(preview, sort_keys=True), "preview must not leak private provider bytes")


def _assert_migration_executed(source: LegacyMigrationSource, executed: JsonObject) -> JsonObject:
    _expect(executed.get("ok") is True and executed.get("wrote_project_registry") is True, "execute must write the registry")
    runtime_result = _first_entry(executed, "runtime_goals", label="migration execute")
    _expect(runtime_result.get("copied") is True, "execute must copy the runtime goal directory")
    lease_path = source.target_runtime / "goals" / source.new_goal_id / "task-leases" / "safe-local.json"
    copied_lease = parse_json_object(lease_path.read_text(encoding="utf-8"))
    _expect(copied_lease.get("goal_id") == source.new_goal_id, "copied lease must carry the migrated goal id")
    identity = (source.target_shadow_directory / "store-identity").read_text(encoding="utf-8")
    _expect(identity.startswith("file:") and identity != source.old_store_identity, "target lineage must be fresh")
    store_paths = sorted(source.target_shadow_directory.glob("authority-store-*.json"))
    _expect(len(store_paths) == 1, "execute must seed exactly one candidate document")
    store = parse_json_object(store_paths[0].read_text(encoding="utf-8"))
    _expect(store.get("goal_id") == source.new_goal_id and store.get("store_identity") == identity, "seeded store must bind the new lineage")
    committed = store.get("committed")
    _expect(store.get("cursor") == "1" and isinstance(committed, list) and len(committed) == 1, "seed must be the first and only commit")
    serialized = json.dumps(store, sort_keys=True)
    for forbidden in (source.old_store_identity, source.legacy_revision, str(source.source_repo), source.private_marker):
        _expect(forbidden not in serialized, "seeded store must not carry any legacy lineage or private byte")
    _expect(not (source.target_shadow_directory / "authority-store-legacy.json").exists(), "legacy document must not migrate")
    seed = _first_entry(executed, "authority_shadow_seeds", label="migration execute")
    _expect(seed.get("goal_id") == source.new_goal_id and seed.get("attempted") is True, "seed must target the migrated goal")
    _expect(seed.get("outcome") == "captured", "seed must be captured")
    return store


def _row_migration_seeds_new_lineage(context: RowContext) -> RowOutcome:
    source = build_legacy_migration_source(
        context.root,
        old_goal_id=unique_goal_id("legacy"),
        new_goal_id=unique_goal_id("migrated"),
    )
    sentinel = b'{"schema_version":"existing","goals":[]}\n'
    source.target_registry.write_bytes(sentinel)
    arguments = _migration_arguments(source)
    _assert_migration_preview(source, run_cli(source, *arguments), sentinel)
    store = _assert_migration_executed(source, run_cli(source, *arguments, "--execute"))
    return passed(seed_outcome="captured", seeded_cursor=str(store.get("cursor")), legacy_lineage_excluded=True)


def _row_dual_runtime_root_consistency(context: RowContext) -> RowOutcome:
    """``--runtime-root`` differs from ``common_runtime_root``: one lineage per goal."""

    workspace = build_goal_workspace(
        context.root,
        goal_id=unique_goal_id("ladder-one-root"),
        handoff_mode="hard_lease",
        shadow_enabled=True,
        runtime_root_binding="cli_override_divergent",
    )
    _expect(
        workspace.registry_runtime_root != workspace.runtime_root,
        "fixture must register a different common_runtime_root than the override",
    )
    added = _add_todo(workspace, "Every hook of one CLI call shares one runtime root.")
    todo_id = str(added["todo_id"])
    acquired = _acquire_lease(
        workspace,
        todo_id=todo_id,
        owner=AGENT_A,
        idempotency_key="ladder-one-root-lease",
    )
    updated = run_cli(
        workspace, "todo", "update", "--goal-id", workspace.goal_id, "--todo-id", todo_id,
        "--note", "Observed under the override root.", "--agent-id", AGENT_A,
    )
    followups = run_cli(
        workspace, "todo", "capture-followups", "--goal-id", workspace.goal_id,
        "--follow-up", "Keep one candidate lineage per goal.",
        "--evidence", "validation://ladder-one-root",
    )
    completed = run_cli(
        workspace, "todo", "complete", "--goal-id", workspace.goal_id, "--todo-id", todo_id,
        "--agent-id", AGENT_A, "--task-lease-idempotency-key", "ladder-one-root-lease",
        "--task-lease-expected-version", _lease_version(acquired, label="acquire"),
        "--evidence", "validation://ladder-one-root-complete", "--no-follow-up",
    )
    observations = [
        _committed_observation(payload, label=label)
        for label, payload in (
            ("todo add", added),
            ("task-lease acquire", acquired),
            ("todo update", updated),
            ("todo capture-followups", followups),
            ("todo complete", completed),
        )
    ]
    identities = {str(evidence.get("store_identity")) for evidence in observations}
    _expect(len(identities) == 1, "every writer family must observe into one store identity")
    document = candidate_document(workspace)
    _expect(document.store_identity in identities, "candidate bytes must carry the observed identity")
    _expect(document.cursor == str(len(observations)), "candidate cursor must equal the observation count")
    _expect(
        todo_id in document.todo_ids and len(document.todo_ids) == 2,
        "head must hold the completed todo and its captured follow-up",
    )
    _expect(
        [lease.get("todo_id") for lease in document.leases] == [todo_id]
        and document.leases[0].get("status") == "released",
        "head must hold exactly the released lease of the completed todo",
    )
    lease_path = workspace.runtime_root / "goals" / workspace.goal_id / "task-leases" / f"{todo_id}.json"
    _expect(lease_path.exists(), "lease state must live under the override root")
    _expect(
        not (workspace.registry_runtime_root / "authority-shadow").exists(),
        "the registry root must not gain a candidate lineage",
    )
    _expect(
        not (workspace.registry_runtime_root / "goals").exists(),
        "the registry root must not gain lease state",
    )
    return passed(
        observations=len(observations),
        store_identities=len(identities),
        candidate_cursor=document.cursor,
        head_todos=len(document.todo_ids),
        head_leases=len(document.leases),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


LADDER_ROWS: tuple[LadderRow, ...] = (
    LadderRow(
        id="s0.file_matrix_twelve_rows",
        stage="0",
        title="Twelve shared lifecycle scenarios pass on the file coordination provider",
        product_path="store_direct",
        gate="deterministic",
        posix_only=False,
        run=_row_file_matrix_twelve_rows,
    ),
    LadderRow(
        id="s0.nokv_live_matrix",
        stage="0",
        title="The same matrix passes on a live NoKV stack with identical outcomes",
        product_path="store_direct",
        gate="env:nokv_legacy",
        posix_only=False,
        run=_row_nokv_live_matrix,
    ),
    LadderRow(
        id="s1.cli_document_decodes_through_ts_store",
        stage="1",
        title="CLI-written candidate documents decode through the TypeScript FileAuthorityStore",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_cli_document_decodes_through_ts_store,
    ),
    LadderRow(
        id="s2b.postgresql_conformance_live",
        stage="2b",
        title="PostgreSQL candidate passes the conformance suite against a live database",
        product_path="store_direct",
        gate="env:postgresql",
        posix_only=False,
        run=_row_postgresql_conformance_live,
    ),
    LadderRow(
        id="s2c1.configure_enable_disable_roundtrip",
        stage="2c1",
        title="configure-goal previews, enables, reads back, and disables the observer",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_configure_enable_disable_roundtrip,
    ),
    LadderRow(
        id="s2c1.every_writer_family_captures",
        stage="2c1",
        title="Every local writer family records a post-commit observation",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_every_writer_family_captures,
    ),
    LadderRow(
        id="s2c1.default_off_isolation",
        stage="2c1",
        title="Default-off goals produce identical responses and no candidate storage",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_default_off_isolation,
    ),
    LadderRow(
        id="s2c1.candidate_failure_preserves_primary",
        stage="2c1",
        title="Candidate construction failure never reverses the primary commit",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_candidate_failure_preserves_primary,
    ),
    LadderRow(
        id="s2c1.crash_gap_loses_observation",
        stage="2c1",
        title="A SIGKILL between primary commit and observer loses only that observation",
        product_path="real_cli",
        gate="deterministic",
        posix_only=True,
        run=_row_crash_gap_loses_observation,
    ),
    LadderRow(
        id="s2c1.dual_runtime_root_consistency",
        stage="2c1",
        title="A --runtime-root override that differs from common_runtime_root keeps one candidate lineage",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_dual_runtime_root_consistency,
    ),
    LadderRow(
        id="s2c1.migration_seeds_new_lineage",
        stage="2c1",
        title="migrate-state excludes the legacy lineage and seeds a fresh candidate",
        product_path="real_cli",
        gate="deterministic",
        posix_only=False,
        run=_row_migration_seeds_new_lineage,
    ),
)

PENDING_ROWS: tuple[PendingRow, ...] = (
    PendingRow("s2a.nokv_live_qualification", "2a", "PR #3819 merge"),
    PendingRow("s2c2.outbox_prepared_then_committed_entries", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.drain_idempotent", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.sigkill_between_primary_write_and_drain", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.sigkill_mid_drain", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.rollback_with_pending_entries", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.parity_equal", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.parity_divergent_detects_foreign_edit", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.migration_seeds_and_drains", "2c2", "Stage 2C parity PRs"),
    PendingRow("s2c2.growth_measurement_gate", "2c2", "Stage 2C parity PRs"),
)


def row_by_id(row_id: str) -> LadderRow:
    for row in LADDER_ROWS:
        if row.id == row_id:
            return row
    raise KeyError(row_id)


# ---------------------------------------------------------------------------
# Gates, redaction, and row execution
# ---------------------------------------------------------------------------


def gate_unverified_reason(gate: str, environ: Mapping[str, str]) -> tuple[str, JsonObject] | None:
    """Return the unverified reason for an env gate whose stack is absent."""

    required = GATE_REQUIREMENTS[gate]
    missing = sorted(name for name in required if not environ.get(name))
    if missing:
        return GATE_UNVERIFIED_REASON[gate], {"missing_variables": missing}
    if NOKV_LIVE_FLAG in required and environ.get(NOKV_LIVE_FLAG) != "1":
        return "nokv_live_flag_not_enabled", {"flag": NOKV_LIVE_FLAG}
    return None


def default_forbidden_tokens(roots: Iterable[Path], environ: Mapping[str, str]) -> list[str]:
    """Substrings whose presence in a report is a privacy leak."""

    tokens: set[str] = set()
    for root in roots:
        tokens.add(str(root))
        tokens.add(str(Path(root).resolve()))
    temp_root = Path(tempfile.gettempdir())
    tokens.update({str(temp_root), str(temp_root.resolve())})
    tokens.add(environ.get("HOME") or str(Path.home()))
    tokens.update({str(REPO_ROOT), str(REPO_ROOT.resolve())})
    for name in (POSTGRES_URL_VARIABLE, *NOKV_STACK_VARIABLES):
        value = environ.get(name)
        if value:
            tokens.add(value)
    return sorted((token for token in tokens if len(token) >= 4), key=len, reverse=True)


def redact(text: str, forbidden: Sequence[str]) -> str:
    for token in forbidden:
        text = text.replace(token, "<redacted>")
    return text


def _failure_result(
    row: LadderRow,
    exc: BaseException,
    *,
    forbidden: Sequence[str],
    started: float,
) -> RowResult:
    reason_code = "assertion_failed" if isinstance(exc, AssertionError) else "row_exception"
    return RowResult(
        row=row,
        status="fail",
        reason_code=reason_code,
        evidence={
            "error_type": type(exc).__name__,
            "message": redact(str(exc), forbidden)[:500],
        },
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def run_row(
    row: LadderRow,
    *,
    root: Path,
    environ: Mapping[str, str] | None = None,
) -> RowResult:
    """Run one row in ``root`` and classify its outcome without raising."""

    started = time.monotonic()
    env: Mapping[str, str] = dict(os.environ) if environ is None else environ
    forbidden = default_forbidden_tokens([root], env)
    if row.posix_only and os.name == "nt":
        return RowResult(row, "unverified", "posix_only", {"platform": os.name}, 0)
    gate = gate_unverified_reason(row.gate, env)
    if gate is not None:
        return RowResult(row, "unverified", gate[0], gate[1], 0)
    try:
        outcome = row.run(RowContext(root=root, environ=env))
    except Exception as exc:
        # Every row failure becomes a typed, redacted result; nothing escapes.
        return _failure_result(row, exc, forbidden=forbidden, started=started)
    if outcome.status not in {"pass", "unverified"}:
        return _failure_result(
            row,
            RowAssertionError(f"row returned unsupported status {outcome.status!r}"),
            forbidden=forbidden,
            started=started,
        )
    return RowResult(
        row=row,
        status=outcome.status,
        reason_code=outcome.reason_code,
        evidence=outcome.evidence,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


# ---------------------------------------------------------------------------
# Report, bindings, privacy scan, exit policy
# ---------------------------------------------------------------------------


def _git_output(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _probe_digests() -> list[JsonObject]:
    digests: list[JsonObject] = []
    for relative in PROBE_SOURCES:
        path = REPO_ROOT / relative
        if path.exists():
            digests.append({"path": relative.as_posix(), "sha256": _sha256_hex(path.read_bytes())})
    return digests


def _nokv_client_config_digest(environ: Mapping[str, str]) -> str | None:
    public = {
        name: environ[name]
        for name in NOKV_STACK_VARIABLES
        if name not in NOKV_SECRET_VARIABLES and environ.get(name)
    }
    if len(public) != len(NOKV_STACK_VARIABLES) - len(NOKV_SECRET_VARIABLES):
        return None
    return _sha256_hex(json.dumps(public, sort_keys=True, separators=(",", ":")))


def _nokv_sdk_version() -> str | None:
    for distribution in ("nokv", "nokv-python"):
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
    return None


def collect_bindings(environ: Mapping[str, str]) -> JsonObject:
    """Pin what the report was produced against; ``None`` means unknown."""

    commit = _git_output("rev-parse", "HEAD")
    status = _git_output("status", "--porcelain")
    postgres_url = environ.get(POSTGRES_URL_VARIABLE)
    return {
        "loopx_commit": commit.strip() if commit else None,
        "loopx_tree_dirty": bool(status.strip()) if status is not None else None,
        "probe_sha256": _probe_digests(),
        "nokv_client_config_sha256": _nokv_client_config_digest(environ),
        "nokv_sdk_version": _nokv_sdk_version(),
        "postgres_url_sha256_prefix": _sha256_hex(postgres_url)[:12] if postgres_url else None,
        "pg_package_version": _pg_package_version(),
    }


def exit_code_for(summary: Mapping[str, int], *, allow_unverified: bool) -> int:
    if summary["fail"] != 0:
        return 1
    if summary["unverified"] != 0 and not allow_unverified:
        return 1
    return 0


def _finalize_report(
    rows: Sequence[JsonObject],
    pending: Sequence[JsonObject],
    bindings: JsonObject,
    *,
    allow_unverified: bool,
    generated_at: str,
) -> JsonObject:
    summary = {status: sum(1 for row in rows if row["status"] == status) for status in ROW_STATUSES}
    summary["pending"] = len(pending)
    return {
        "schema_version": REPORT_SCHEMA,
        "generated_at": generated_at,
        "rows": list(rows),
        "pending": list(pending),
        "summary": summary,
        "bindings": bindings,
        "exit_policy": {
            "allow_unverified": allow_unverified,
            "exit_code": exit_code_for(summary, allow_unverified=allow_unverified),
            "rule": EXIT_POLICY_RULE,
        },
    }


def _leaked_tokens(value: object, forbidden: Sequence[str]) -> list[str]:
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return [token for token in forbidden if token in serialized]


def assert_public_safe(report: JsonObject, *, forbidden: Sequence[str]) -> JsonObject:
    """Turn any leak of a forbidden substring into ``fail/privacy_violation``."""

    rows: list[JsonObject] = []
    for row in report["rows"]:
        leaked = _leaked_tokens(row, forbidden)
        if leaked:
            rows.append(
                {
                    **row,
                    "status": "fail",
                    "reason_code": "privacy_violation",
                    "evidence": {"leaked_token_count": len(leaked)},
                }
            )
        else:
            rows.append(dict(row))
    bindings = dict(report["bindings"])
    if _leaked_tokens(bindings, forbidden):
        bindings = {key: None for key in bindings}
        bindings["privacy_violation"] = True
    return _finalize_report(
        rows,
        report["pending"],
        bindings,
        allow_unverified=bool(report["exit_policy"]["allow_unverified"]),
        generated_at=str(report["generated_at"]),
    )


def build_report(
    results: Sequence[RowResult],
    *,
    pending: Sequence[PendingRow],
    allow_unverified: bool,
    environ: Mapping[str, str] | None = None,
    forbidden: Sequence[str] | None = None,
) -> JsonObject:
    """Assemble the report and run the privacy scan over it."""

    env: Mapping[str, str] = dict(os.environ) if environ is None else environ
    tokens = list(forbidden) if forbidden is not None else default_forbidden_tokens([], env)
    report = _finalize_report(
        [result.as_dict() for result in results],
        [row.describe() for row in pending],
        collect_bindings(env),
        allow_unverified=allow_unverified,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return assert_public_safe(report, forbidden=tokens)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ladder",
        description="Run the shared-goal-authority stage ladder against this checkout.",
    )
    parser.add_argument("--stage", action="append", choices=STAGES, help="Only run rows of this stage; repeatable.")
    parser.add_argument("--row", action="append", help="Only run this row id; repeatable.")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Exit 0 even when env-gated rows could not run; failures still exit 1.",
    )
    parser.add_argument("--report-json", help="Write the JSON report to this path as well as stdout.")
    parser.add_argument("--list", action="store_true", help="Print the row registry and pending rows, then exit.")
    return parser


def _selected(
    stages: Sequence[str] | None,
    row_ids: Sequence[str] | None,
) -> tuple[list[LadderRow], list[PendingRow]]:
    rows = [row for row in LADDER_ROWS if not stages or row.stage in stages]
    pending = [row for row in PENDING_ROWS if not stages or row.stage in stages]
    if row_ids:
        wanted = set(row_ids)
        rows = [row for row in rows if row.id in wanted]
        pending = [row for row in pending if row.id in wanted]
    return rows, pending


def _run_selected(rows: Sequence[LadderRow], environ: Mapping[str, str]) -> tuple[list[RowResult], list[str]]:
    results: list[RowResult] = []
    tokens: set[str] = set()
    for row in rows:
        with tempfile.TemporaryDirectory(prefix="loopx-authority-ladder-") as scratch:
            root = Path(scratch)
            tokens.update(default_forbidden_tokens([root], environ))
            results.append(run_row(row, root=root, environ=environ))
    return results, sorted(tokens, key=len, reverse=True)


def _print_summary(report: JsonObject) -> None:
    for status in ("fail", "unverified"):
        ids = [f"{row['id']} ({row['reason_code']})" for row in report["rows"] if row["status"] == status]
        if ids:
            print(f"{status} rows: {', '.join(ids)}", file=sys.stderr)
    print(
        "summary: " + ", ".join(f"{key}={value}" for key, value in sorted(report["summary"].items()))
        + f"; exit_code={report['exit_policy']['exit_code']}",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    rows, pending = _selected(args.stage, args.row)
    if args.list:
        listing = {
            "schema_version": LIST_SCHEMA,
            "rows": [row.describe() for row in rows],
            "pending": [row.describe() for row in pending],
        }
        print(json.dumps(listing, indent=2, sort_keys=True))
        return 0
    if not rows and not pending:
        print("no rows match the requested selection", file=sys.stderr)
        return 2
    environ = dict(os.environ)
    results, tokens = _run_selected(rows, environ)
    report = build_report(
        results,
        pending=pending,
        allow_unverified=bool(args.allow_unverified),
        environ=environ,
        forbidden=tokens or default_forbidden_tokens([], environ),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report_json:
        Path(args.report_json).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    _print_summary(report)
    return int(report["exit_policy"]["exit_code"])


__all__ = [
    "EXIT_POLICY_RULE",
    "FILE_MATRIX_ROWS",
    "GATES",
    "GATE_REQUIREMENTS",
    "LADDER_ROWS",
    "NOKV_LIVE_FLAG",
    "NOKV_STACK_VARIABLES",
    "PENDING_ROWS",
    "POSTGRES_URL_VARIABLE",
    "PRODUCT_PATHS",
    "REPORT_SCHEMA",
    "ROW_STATUSES",
    "STAGES",
    "LadderRow",
    "PendingRow",
    "RowAssertionError",
    "RowContext",
    "RowOutcome",
    "RowResult",
    "assert_public_safe",
    "build_report",
    "collect_bindings",
    "default_forbidden_tokens",
    "exit_code_for",
    "gate_unverified_reason",
    "main",
    "passed",
    "redact",
    "row_by_id",
    "run_row",
    "unverified",
]


if __name__ == "__main__":
    raise SystemExit(main())
