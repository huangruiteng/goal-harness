"""Generic observable-artifact-handle protocol for external long-running work.

``observable_artifact_handle_v0`` is a default generic capability — it
describes external jobs, CI runs, benchmark attempts, evaluations, deploys,
or other long tasks with a compact handle, allowed poll command, artifact
refs, terminal markers, and read boundary.  It does NOT assume a benchmark,
CI, deployment, or ML experiment adapter.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

OBSERVABLE_ARTIFACT_HANDLE_SCHEMA_VERSION = "observable_artifact_handle_v0"
OBSERVABLE_ARTIFACT_HANDLE_POLICY_SCHEMA_VERSION = (
    "observable_artifact_handle_policy_v0"
)

# ---------------------------------------------------------------------------
# Allowed-value sets
# ---------------------------------------------------------------------------

ALLOWED_HANDLE_STATES = frozenset(
    {
        "queued",
        "starting",
        "running",
        "completed",
        "failed",
        "cancelled",
        "unknown",
    }
)
"""Process states an observable handle may report."""

TERMINAL_MARKERS = frozenset({"completed", "failed", "cancelled"})
"""States that mark a handle as terminal (no further poll expected)."""

ALLOWED_HANDLE_KINDS = frozenset(
    {
        "ci_run",
        "benchmark_attempt",
        "evaluation",
        "deploy",
        "generic",
    }
)
"""Kinds of external work — labels only, no adapter baked in."""

ALLOWED_POLL_OBSERVATIONS = frozenset(
    {
        "task_state",
        "created_marker",
        "fail_marker",
        "done_marker",
        "compact_result_refs",
        "compact_artifact_refs",
    }
)

DEFAULT_READ_BOUNDARY = {
    "compact_only": True,
    "raw_logs_allowed": False,
    "raw_command_allowed": False,
    "raw_env_allowed": False,
    "raw_artifacts_allowed": False,
    "private_paths_allowed": False,
    "raw_handle_payload_recorded": False,
}


# ---------------------------------------------------------------------------
# Public-safe validators (adapt the ml_experiment / observable_handles style)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")

_ABSOLUTE_PATH_RE = re.compile(
    r"(^|[\s:=])(?:"
    + "/Users/"
    + "|/private/|/tmp/|~[/\\s]|[A-Za-z]:\\\\)"
)
_URL_OR_REMOTE_RE = re.compile(
    r"(?i)\b(?:https?|file|s3|gs|tos|hdfs)://"
)
_PRIVATE_MARKER_TERMS = [
    "authorization:",
    r"bearer\s+[A-Za-z0-9._-]+",
    r"api[_-]?" + "key",
    "password",
    "secret",
    r"begin (?:rsa |open)?private " + "key",
    "larkoffice",
    r"feishu\.cn",
    "bytedance",
]
_PRIVATE_MARKER_RE = re.compile(
    r"(?i)(" + "|".join(_PRIVATE_MARKER_TERMS) + ")"
)


def _compact_public_token(value: str, *, field: str) -> str:
    """Validate and return a compact public-safe identifier token."""
    token = str(value or "").strip()
    if not token:
        raise ValueError(f"{field} must be non-empty")
    if not _TOKEN_RE.match(token):
        raise ValueError(
            f"{field} must be a compact token using letters, digits, "
            "dot, colon, dash, or underscore (max 80 chars)"
        )
    return token


def _compact_public_text(value: str, *, field: str, max_len: int = 160) -> str:
    """Validate and return compact public-safe display text."""
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(
            f"{field} is too long for a compact public-safe field"
        )
    if ".." in text:
        raise ValueError(
            f"{field} must not contain parent-directory markers"
        )
    if _ABSOLUTE_PATH_RE.search(text) or text.startswith(("/", "~")):
        raise ValueError(
            f"{field} must use a public alias, not a local or private path"
        )
    if _URL_OR_REMOTE_RE.search(text):
        raise ValueError(
            f"{field} must use a public alias, not a raw URL or remote path"
        )
    if _PRIVATE_MARKER_RE.search(text):
        raise ValueError(
            f"{field} contains a private or credential-like marker"
        )
    return text


def _compact_public_text_list(
    values: Iterable[str] | None, *, field: str, max_len: int = 160
) -> list[str]:
    """Validate a list of compact public-safe labels."""
    return [
        _compact_public_text(str(v), field=f"{field}[]", max_len=max_len)
        for v in (values or [])
    ]


def _public_or_redacted_ref(
    value: str | None, *, field: str
) -> dict[str, Any] | None:
    """Return an alias ref for public-safe text, or a redacted digest."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return {
            "kind": "alias",
            "value": _compact_public_text(str(value), field=field),
            "raw_recorded": False,
        }
    except ValueError:
        digest = hashlib.sha256(
            str(value).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "kind": "redacted_ref",
            "value": f"redacted:{digest}",
            "raw_recorded": False,
        }


def _public_or_redacted_ref_list(
    values: Iterable[str] | None, *, field: str
) -> list[dict[str, Any]]:
    return [
        ref
        for ref in (
            _public_or_redacted_ref(str(v), field=f"{field}[]")
            for v in (values or [])
        )
        if ref is not None
    ]


# ---------------------------------------------------------------------------
# Dataclasses (frozen, typed model)
# ---------------------------------------------------------------------------

class ArtifactHandleState(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self.value in TERMINAL_MARKERS


class ArtifactHandleKind(StrEnum):
    CI_RUN = "ci_run"
    BENCHMARK_ATTEMPT = "benchmark_attempt"
    EVALUATION = "evaluation"
    DEPLOY = "deploy"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class ArtifactReadBoundary:
    """Controls what raw/private data may be read from an artifact handle."""

    compact_only: bool = True
    raw_logs_allowed: bool = False
    raw_command_allowed: bool = False
    raw_env_allowed: bool = False
    raw_artifacts_allowed: bool = False
    private_paths_allowed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "compact_only": self.compact_only,
            "raw_logs_allowed": self.raw_logs_allowed,
            "raw_command_allowed": self.raw_command_allowed,
            "raw_env_allowed": self.raw_env_allowed,
            "raw_artifacts_allowed": self.raw_artifacts_allowed,
            "private_paths_allowed": self.private_paths_allowed,
            "raw_handle_payload_recorded": False,
        }


@dataclass(frozen=True, slots=True)
class PollContract:
    """Describes what observations are allowed and how polling is constrained."""

    allowed_observations: tuple[str, ...]
    poll_interval_min_seconds: int = 30
    max_polls_before_terminal_required: int = 120
    raw_logs_recorded: bool = False
    raw_command_recorded: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed_observations": list(self.allowed_observations),
            "poll_interval_min_seconds": self.poll_interval_min_seconds,
            "max_polls_before_terminal_required": (
                self.max_polls_before_terminal_required
            ),
            "raw_logs_recorded": self.raw_logs_recorded,
            "raw_command_recorded": self.raw_command_recorded,
            "raw_env_recorded": False,
        }


@dataclass(frozen=True, slots=True)
class ObservableArtifactHandle:
    """Compact, public-safe handle for an external long-running task.

    This is the core typed model for ``observable_artifact_handle_v0``.
    """

    handle_id: str
    handle_kind: ArtifactHandleKind
    display_name: str
    state: ArtifactHandleState
    allowed_poll_command: str
    artifact_refs: tuple[str, ...] = ()
    terminal_markers: tuple[str, ...] = ()
    read_boundary: ArtifactReadBoundary = field(default_factory=ArtifactReadBoundary)
    poll_contract: PollContract | None = None
    recommended_next_action: str = "poll_observable_handle"

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal

    @property
    def terminal_marker_set(self) -> frozenset[str]:
        base = set(TERMINAL_MARKERS)
        base.update(self.terminal_markers)
        return frozenset(base)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OBSERVABLE_ARTIFACT_HANDLE_SCHEMA_VERSION,
            "handle_id": self.handle_id,
            "handle_kind": self.handle_kind.value,
            "display_name": self.display_name,
            "state": self.state.value,
            "is_terminal": self.is_terminal,
            "terminal_markers": sorted(self.terminal_marker_set),
            "allowed_poll_command": {
                "command_label": self.allowed_poll_command,
                "argv_recorded": False,
                "raw_command_recorded": False,
            },
            "artifact_refs": [
                {"kind": "alias", "value": ref, "raw_recorded": False}
                for ref in self.artifact_refs
            ],
            "artifact_ref_count": len(self.artifact_refs),
            "read_boundary": self.read_boundary.as_dict(),
            "poll_contract": (
                self.poll_contract.as_dict()
                if self.poll_contract
                else PollContract(
                    allowed_observations=("task_state",)
                ).as_dict()
            ),
            "recommended_next_action": self.recommended_next_action,
            "launch_actions_enabled": False,
            "production_actions_enabled": False,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_observable_artifact_handle(
    *,
    handle_id: str,
    handle_kind: str = "generic",
    display_name: str,
    state: str = "unknown",
    allowed_poll_command: str = "loopx observe",
    artifact_refs: Iterable[str] | None = None,
    terminal_markers: Iterable[str] | None = None,
    compact_only: bool = True,
    raw_logs_allowed: bool = False,
    raw_command_allowed: bool = False,
    raw_env_allowed: bool = False,
    raw_artifacts_allowed: bool = False,
    private_paths_allowed: bool = False,
    poll_observations: Iterable[str] | None = None,
    poll_interval_min_seconds: int = 30,
    recommended_next_action: str = "poll_observable_handle",
) -> dict[str, Any]:
    """Build a public-safe observable artifact handle.

    All inputs are validated against compact public-safe rules.  Paths, URLs,
    credentials, and private markers are rejected before the handle is built.
    """

    # --- validate handle identity ---
    compact_handle_id = _compact_public_token(handle_id, field="handle_id")
    if handle_kind not in ALLOWED_HANDLE_KINDS:
        raise ValueError(
            f"handle_kind must be one of {sorted(ALLOWED_HANDLE_KINDS)}"
        )
    compact_display_name = _compact_public_text(
        display_name, field="display_name", max_len=160
    )

    # --- validate state ---
    compact_state = str(state or "unknown").strip().lower()
    if compact_state not in ALLOWED_HANDLE_STATES:
        compact_state = "unknown"

    # --- validate poll command ---
    compact_poll_command = _compact_public_text(
        allowed_poll_command,
        field="allowed_poll_command",
        max_len=200,
    )

    # --- validate artifact refs ---
    compact_refs = tuple(
        _compact_public_text(str(ref), field="artifact_refs", max_len=160)
        for ref in (artifact_refs or [])
    )

    # --- validate terminal markers ---
    extra_markers: tuple[str, ...] = ()
    if terminal_markers:
        extra_markers = tuple(
            _compact_public_token(str(m), field="terminal_markers")
            for m in terminal_markers
        )

    # --- poll observations ---
    poll_obs = tuple(
        str(obs).strip()
        for obs in (poll_observations or ["task_state"])
        if str(obs).strip() in ALLOWED_POLL_OBSERVATIONS
    )
    if not poll_obs:
        poll_obs = ("task_state",)

    # --- assemble typed handle ---
    handle = ObservableArtifactHandle(
        handle_id=compact_handle_id,
        handle_kind=ArtifactHandleKind(handle_kind),
        display_name=compact_display_name,
        state=ArtifactHandleState(compact_state),
        allowed_poll_command=compact_poll_command,
        artifact_refs=compact_refs,
        terminal_markers=extra_markers,
        read_boundary=ArtifactReadBoundary(
            compact_only=bool(compact_only),
            raw_logs_allowed=bool(raw_logs_allowed),
            raw_command_allowed=bool(raw_command_allowed),
            raw_env_allowed=bool(raw_env_allowed),
            raw_artifacts_allowed=bool(raw_artifacts_allowed),
            private_paths_allowed=bool(private_paths_allowed),
        ),
        poll_contract=PollContract(
            allowed_observations=poll_obs,
            poll_interval_min_seconds=int(poll_interval_min_seconds),
        ),
        recommended_next_action=_compact_public_text(
            recommended_next_action,
            field="recommended_next_action",
            max_len=160,
        ),
    )

    result = handle.as_dict()
    result["ok"] = True
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_observable_artifact_handle(
    handle: dict[str, Any],
) -> dict[str, Any]:
    """Validate a serialized observable artifact handle against the schema.

    Returns ``{"ok": True, ...}`` or ``{"ok": False, "errors": [...]}``.
    """
    errors: list[str] = []

    schema = str(handle.get("schema_version") or "")
    if schema != OBSERVABLE_ARTIFACT_HANDLE_SCHEMA_VERSION:
        errors.append(
            f"expected schema_version {OBSERVABLE_ARTIFACT_HANDLE_SCHEMA_VERSION}, "
            f"got {schema or '<missing>'}"
        )

    handle_id = str(handle.get("handle_id") or "").strip()
    if not handle_id:
        errors.append("handle_id is required")
    elif not _TOKEN_RE.match(handle_id):
        errors.append("handle_id must be a compact token")

    kind = str(handle.get("handle_kind") or "")
    if kind not in ALLOWED_HANDLE_KINDS:
        errors.append(
            f"handle_kind must be one of {sorted(ALLOWED_HANDLE_KINDS)}"
        )

    display_name = str(handle.get("display_name") or "").strip()
    if not display_name:
        errors.append("display_name is required")

    state = str(handle.get("state") or "").strip()
    if state not in ALLOWED_HANDLE_STATES:
        errors.append(
            f"state must be one of {sorted(ALLOWED_HANDLE_STATES)}"
        )

    poll_cmd = handle.get("allowed_poll_command")
    if isinstance(poll_cmd, dict):
        cmd_label = str(poll_cmd.get("command_label") or "").strip()
        if not cmd_label:
            errors.append("allowed_poll_command.command_label is required")
    else:
        errors.append("allowed_poll_command must be a dict with command_label")

    boundary = (
        handle.get("read_boundary")
        if isinstance(handle.get("read_boundary"), dict)
        else {}
    )
    if boundary.get("raw_handle_payload_recorded") is not False:
        errors.append("read_boundary.raw_handle_payload_recorded must be false")

    if handle.get("launch_actions_enabled") is not False:
        errors.append("launch_actions_enabled must be false")

    return {
        "schema_version": "observable_artifact_handle_validation_v0",
        "ok": not errors,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def project_observable_artifact_handle(
    handle: dict[str, Any],
) -> dict[str, Any]:
    """Project an observable artifact handle into first-screen status fields."""

    validation = validate_observable_artifact_handle(handle)
    state = str(handle.get("state") or "unknown")
    is_terminal = state in TERMINAL_MARKERS
    handle_id = str(handle.get("handle_id") or "")
    kind = str(handle.get("handle_kind") or "generic")

    if is_terminal:
        next_action = "ingest_compact_closeout"
        waiting_on = "none"
    elif state in {"queued", "starting", "running"}:
        next_action = "poll_observable_handle"
        waiting_on = "external_system"
    else:
        next_action = "investigate_handle_state"
        waiting_on = "operator"

    return {
        "schema_version": "observable_artifact_handle_projection_v0",
        "handle_id": handle_id,
        "handle_kind": kind,
        "state": state,
        "is_terminal": is_terminal,
        "first_screen": {
            "waiting_on": waiting_on,
            "next_safe_action": next_action,
            "operator_action_required": waiting_on == "operator",
        },
        "artifact_ref_count": len(
            handle.get("artifact_refs") or []
        ),
        "read_boundary": handle.get("read_boundary"),
        "validation": validation,
        "truth_contract": {
            "projection_is_writable": False,
            "write_authority": "none",
            "handle_is_source_of_truth": False,
            "launch_actions_enabled": False,
            "compact_observation_only": True,
        },
    }


# ---------------------------------------------------------------------------
# Policy (terminal markers, next-action routing)
# ---------------------------------------------------------------------------

def build_observable_artifact_handle_policy(
    handle: dict[str, Any],
) -> dict[str, Any]:
    """Return a public-safe polling/cleanup policy for an observable handle.

    The policy is a read-only projection — it does not inspect raw logs,
    credentials, local paths, or private payloads.
    """

    state = str(handle.get("state") or "unknown").strip().lower()
    handle_id = str(handle.get("handle_id") or "")
    kind = str(handle.get("handle_kind") or "generic")
    is_terminal = state in TERMINAL_MARKERS
    is_active = state in {"queued", "starting", "running"}
    ref_count = len(handle.get("artifact_refs") or [])

    poll_allowed = is_active and not is_terminal
    cleanup_required = is_terminal

    if is_terminal:
        if state == "completed" and ref_count > 0:
            next_action = (
                "ingest_compact_artifact_refs_and_disable_poll"
            )
        else:
            next_action = "disable_poll_and_record_terminal_state"
    elif is_active:
        next_action = "poll_observable_handle"
    elif not is_active and not is_terminal:
        next_action = "investigate_handle_state"
    else:
        next_action = "continue_compact_observation"

    return {
        "schema_version": OBSERVABLE_ARTIFACT_HANDLE_POLICY_SCHEMA_VERSION,
        "handle_id": handle_id,
        "handle_kind": kind,
        "state": state,
        "is_terminal": is_terminal,
        "is_active": is_active,
        "poll_allowed": poll_allowed,
        "cleanup_required": cleanup_required,
        "next_action": next_action,
        "boundary": {
            "compact_only": True,
            "raw_logs_read": False,
            "raw_command_read": False,
            "raw_env_read": False,
            "private_paths_read": False,
            "raw_handle_payload_recorded": False,
        },
    }


# ---------------------------------------------------------------------------
# Synthetic fixture builder
# ---------------------------------------------------------------------------

def build_observable_artifact_handle_fixture(
    *,
    handle_id: str = "demo-handle-001",
    handle_kind: str = "generic",
    display_name: str = "Demo Long-Running Task",
    state: str = "running",
) -> dict[str, Any]:
    """Build a synthetic public-safe fixture for testing and demos."""

    extra_markers = ("rolled_back",) if handle_kind == "deploy" else ()
    poll_cmd = {
        "ci_run": "ci status --job-id demo-ci-run",
        "benchmark_attempt": "loopx benchmark status --run-id demo-bench",
        "evaluation": "loopx eval status --eval-id demo-eval",
        "deploy": "kubectl rollout status deployment/demo-app",
        "generic": "loopx observe --handle-id demo-handle-001",
    }.get(handle_kind, "loopx observe --handle-id demo-handle-001")

    poll_obs = list(ALLOWED_POLL_OBSERVATIONS)

    return build_observable_artifact_handle(
        handle_id=handle_id,
        handle_kind=handle_kind,
        display_name=display_name,
        state=state,
        allowed_poll_command=poll_cmd,
        artifact_refs=["artifacts/demo-result.json"],
        terminal_markers=extra_markers,
        compact_only=True,
        poll_observations=poll_obs,
        recommended_next_action=(
            "poll_observable_handle"
            if state in {"queued", "starting", "running"}
            else "ingest_compact_closeout"
        ),
    )


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def render_observable_artifact_handle_markdown(
    handle: dict[str, Any],
) -> str:
    """Render a compact public-safe markdown summary of the handle."""

    handle_id = handle.get("handle_id", "?")
    kind = handle.get("handle_kind", "generic")
    display_name = handle.get("display_name", "?")
    state = handle.get("state", "unknown")
    is_terminal = state in TERMINAL_MARKERS

    poll_cmd = handle.get("allowed_poll_command")
    cmd_label = (
        poll_cmd.get("command_label", "unknown")
        if isinstance(poll_cmd, dict)
        else str(poll_cmd or "unknown")
    )

    refs = handle.get("artifact_refs") or []
    ref_labels = []
    for ref in refs:
        if isinstance(ref, dict):
            ref_labels.append(str(ref.get("value", "?")))
        else:
            ref_labels.append(str(ref))

    policy = (
        handle.get("recommended_next_action", "")
        or "poll_observable_handle"
    )

    lines = [
        "# Observable Artifact Handle",
        "",
        f"- handle: `{handle_id}`",
        f"- kind: `{kind}`",
        f"- name: `{display_name}`",
        f"- state: `{state}` (terminal: `{is_terminal}`)",
        f"- poll command: `{cmd_label}`",
        "- artifact refs: "
        + ", ".join(f"`{ref}`" for ref in ref_labels[:8]),
        f"- artifact ref count: {len(refs)}",
        f"- launch actions enabled: "
        f"`{handle.get('launch_actions_enabled')}`",
        f"- production actions enabled: "
        f"`{handle.get('production_actions_enabled')}`",
        f"- next action: `{policy}`",
        "",
        "## Read Boundary",
        "",
    ]

    boundary = (
        handle.get("read_boundary")
        if isinstance(handle.get("read_boundary"), dict)
        else {}
    )
    for key, value in boundary.items():
        lines.append(f"- `{key}`: `{value}`")

    return "\n".join(lines) + "\n"
