"""Tests for ``loopx.observable_artifact_handle``."""

from __future__ import annotations

import pytest

from loopx.observable_artifact_handle import (
    ALLOWED_HANDLE_KINDS,
    ALLOWED_HANDLE_STATES,
    TERMINAL_MARKERS,
    ArtifactHandleKind,
    ArtifactHandleState,
    ArtifactReadBoundary,
    ObservableArtifactHandle,
    PollContract,
    build_observable_artifact_handle,
    build_observable_artifact_handle_fixture,
    build_observable_artifact_handle_policy,
    project_observable_artifact_handle,
    render_observable_artifact_handle_markdown,
    validate_observable_artifact_handle,
)


# ---------------------------------------------------------------------------
# Builder — happy path
# ---------------------------------------------------------------------------

def test_build_observable_artifact_handle_success() -> None:
    """Full handle with all fields returns ok=True."""
    result = build_observable_artifact_handle(
        handle_id="ci-build-42",
        handle_kind="ci_run",
        display_name="Main CI Build #42",
        state="running",
        allowed_poll_command="ci status --job-id build-42",
        artifact_refs=["artifacts/coverage.json", "artifacts/lint.txt"],
        terminal_markers=(),
        poll_observations=["task_state", "done_marker", "compact_artifact_refs"],
        recommended_next_action="poll_observable_handle",
    )
    assert result["ok"] is True
    assert result["schema_version"] == "observable_artifact_handle_v0"
    assert result["handle_id"] == "ci-build-42"
    assert result["handle_kind"] == "ci_run"
    assert result["state"] == "running"
    assert result["is_terminal"] is False
    assert result["artifact_ref_count"] == 2
    assert result["launch_actions_enabled"] is False
    assert result["production_actions_enabled"] is False
    # poll command is stored as dict
    poll = result["allowed_poll_command"]
    assert isinstance(poll, dict)
    assert poll["command_label"] == "ci status --job-id build-42"
    assert poll["argv_recorded"] is False


def test_build_observable_artifact_handle_minimal() -> None:
    """Minimal required fields produce a valid handle."""
    result = build_observable_artifact_handle(
        handle_id="minimal-1",
        display_name="Minimal Handle",
    )
    assert result["ok"] is True
    assert result["handle_kind"] == "generic"
    assert result["state"] == "unknown"
    assert result["is_terminal"] is False
    assert result["artifact_ref_count"] == 0


# ---------------------------------------------------------------------------
# Terminal state detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("state", "is_terminal"),
    [
        ("completed", True),
        ("failed", True),
        ("cancelled", True),
        ("running", False),
        ("queued", False),
        ("starting", False),
        ("unknown", False),
    ],
)
def test_terminal_state_detection(state: str, is_terminal: bool) -> None:
    """Terminal markers are correctly detected."""
    result = build_observable_artifact_handle(
        handle_id="state-test",
        display_name="State Test",
        state=state,
    )
    assert result["is_terminal"] == is_terminal


def test_state_enum_is_terminal() -> None:
    """ArtifactHandleState enum reports terminal correctly."""
    assert ArtifactHandleState.COMPLETED.is_terminal is True
    assert ArtifactHandleState.FAILED.is_terminal is True
    assert ArtifactHandleState.CANCELLED.is_terminal is True
    assert ArtifactHandleState.RUNNING.is_terminal is False
    assert ArtifactHandleState.QUEUED.is_terminal is False


# ---------------------------------------------------------------------------
# Read boundary
# ---------------------------------------------------------------------------

def test_read_boundary_defaults_deny_raw() -> None:
    """Default ArtifactReadBoundary denies all raw/private access."""
    boundary = ArtifactReadBoundary()
    assert boundary.compact_only is True
    assert boundary.raw_logs_allowed is False
    assert boundary.raw_command_allowed is False
    assert boundary.raw_env_allowed is False
    assert boundary.raw_artifacts_allowed is False
    assert boundary.private_paths_allowed is False

    d = boundary.as_dict()
    assert d["compact_only"] is True
    assert d["raw_logs_allowed"] is False
    assert d["raw_handle_payload_recorded"] is False


def test_read_boundary_can_relax() -> None:
    """Read boundary can be relaxed per-field."""
    boundary = ArtifactReadBoundary(
        compact_only=False,
        raw_logs_allowed=True,
        raw_artifacts_allowed=True,
    )
    assert boundary.compact_only is False
    assert boundary.raw_logs_allowed is True
    assert boundary.raw_artifacts_allowed is True
    assert boundary.raw_env_allowed is False  # still denied

    result = build_observable_artifact_handle(
        handle_id="relaxed-boundary",
        display_name="Relaxed Read Boundary",
        compact_only=False,
        raw_logs_allowed=True,
        raw_artifacts_allowed=True,
    )
    boundary_dict = result["read_boundary"]
    assert boundary_dict["compact_only"] is False
    assert boundary_dict["raw_logs_allowed"] is True
    assert boundary_dict["raw_artifacts_allowed"] is True


# ---------------------------------------------------------------------------
# Rejection of private/unsafe inputs
# ---------------------------------------------------------------------------

def test_rejects_absolute_path_in_artifact_refs() -> None:
    """Artifact refs must not contain absolute paths."""
    with pytest.raises(ValueError, match="artifact_refs"):
        build_observable_artifact_handle(
            handle_id="bad-path",
            display_name="Bad Path Handle",
            artifact_refs=["/Users/alice/results.json"],
        )


def test_rejects_windows_absolute_path() -> None:
    """Windows absolute paths are rejected."""
    with pytest.raises(ValueError, match="artifact_refs"):
        build_observable_artifact_handle(
            handle_id="bad-win-path",
            display_name="Bad Windows Path",
            artifact_refs=[r"C:\Users\alice\results.json"],
        )


def test_rejects_url_in_artifact_refs() -> None:
    """Artifact refs must not contain raw URLs."""
    with pytest.raises(ValueError, match="artifact_refs"):
        build_observable_artifact_handle(
            handle_id="bad-url",
            display_name="Bad URL Handle",
            artifact_refs=["https://example.com/artifact.json"],
        )


def test_rejects_credential_markers_in_display_name() -> None:
    """Fields with credential-like markers are rejected."""
    with pytest.raises(ValueError, match="display_name"):
        build_observable_artifact_handle(
            handle_id="leak-cred",
            display_name="Run with password=abc123",
        )


def test_rejects_parent_directory_markers() -> None:
    """'..' parent-directory markers are rejected."""
    with pytest.raises(ValueError, match="artifact_refs"):
        build_observable_artifact_handle(
            handle_id="bad-dotdot",
            display_name="DotDot Test",
            artifact_refs=["../../etc/passwd"],
        )


def test_handle_id_is_compact_token() -> None:
    """Handle ID must match the compact token pattern."""
    # Valid
    result = build_observable_artifact_handle(
        handle_id="valid-id.42:test_run",
        display_name="Token Test",
    )
    assert result["ok"] is True

    # Invalid — contains spaces
    with pytest.raises(ValueError, match="handle_id"):
        build_observable_artifact_handle(
            handle_id="not a token",
            display_name="Bad Token",
        )

    # Invalid — empty
    with pytest.raises(ValueError, match="handle_id"):
        build_observable_artifact_handle(
            handle_id="",
            display_name="Empty Token",
        )


def test_handle_kind_must_be_allowed() -> None:
    """Handle kind must be one of the allowed set."""
    result = build_observable_artifact_handle(
        handle_id="kind-test",
        display_name="Kind Test",
        handle_kind="deploy",
    )
    assert result["handle_kind"] == "deploy"

    with pytest.raises(ValueError, match="handle_kind"):
        build_observable_artifact_handle(
            handle_id="bad-kind",
            display_name="Bad Kind",
            handle_kind="ml_experiment",
        )


# ---------------------------------------------------------------------------
# PollContract
# ---------------------------------------------------------------------------

def test_poll_contract_defaults() -> None:
    """PollContract has sensible defaults."""
    pc = PollContract(allowed_observations=("task_state",))
    assert pc.poll_interval_min_seconds == 30
    assert pc.max_polls_before_terminal_required == 120
    assert pc.raw_logs_recorded is False

    d = pc.as_dict()
    assert d["allowed_observations"] == ["task_state"]
    assert d["poll_interval_min_seconds"] == 30


def test_poll_observations_are_validated() -> None:
    """Only allowed observation labels are kept."""
    result = build_observable_artifact_handle(
        handle_id="poll-obs",
        display_name="Poll Obs Test",
        poll_observations=["task_state", "unknown_obs", "done_marker"],
    )
    poll = result["poll_contract"]
    assert "task_state" in poll["allowed_observations"]
    assert "done_marker" in poll["allowed_observations"]
    assert "unknown_obs" not in poll["allowed_observations"]


# ---------------------------------------------------------------------------
# Custom terminal markers
# ---------------------------------------------------------------------------

def test_custom_terminal_markers() -> None:
    """Custom terminal markers extend the base set."""
    result = build_observable_artifact_handle(
        handle_id="custom-term",
        display_name="Custom Terminal Markers",
        terminal_markers=["rolled_back", "superseded"],
        state="rolled_back",
    )
    # "rolled_back" is not in base TERMINAL_MARKERS, so is_terminal stays False
    # unless state matches TERMINAL_MARKERS.  Custom markers enrich the set
    # reported in the handle but do NOT override the state field's terminality.
    assert "rolled_back" in result["terminal_markers"]
    assert "superseded" in result["terminal_markers"]
    assert "completed" in result["terminal_markers"]


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(ALLOWED_HANDLE_KINDS))
def test_fixture_covers_all_handle_kinds(kind: str) -> None:
    """Fixture builder works for every allowed handle kind."""
    result = build_observable_artifact_handle_fixture(
        handle_id=f"fixture-{kind}",
        handle_kind=kind,
        display_name=f"Fixture {kind}",
    )
    assert result["ok"] is True
    assert result["handle_kind"] == kind


def test_fixture_deploy_has_extra_terminal_marker() -> None:
    """Deploy fixtures include 'rolled_back' marker."""
    result = build_observable_artifact_handle_fixture(
        handle_kind="deploy",
    )
    assert "rolled_back" in result["terminal_markers"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_validate_accepts_valid_handle() -> None:
    """Validation accepts a well-formed handle."""
    handle = build_observable_artifact_handle_fixture()
    result = validate_observable_artifact_handle(handle)
    assert result["ok"] is True
    assert result["errors"] == []


def test_validate_rejects_wrong_schema() -> None:
    """Validation rejects wrong schema_version."""
    result = validate_observable_artifact_handle(
        {"schema_version": "wrong_v1", "handle_id": "x"}
    )
    assert result["ok"] is False
    assert any("schema_version" in e for e in result["errors"])


def test_validate_rejects_missing_handle_id() -> None:
    """Validation rejects missing handle_id."""
    result = validate_observable_artifact_handle(
        {"schema_version": "observable_artifact_handle_v0"}
    )
    assert result["ok"] is False
    assert any("handle_id" in e for e in result["errors"])


def test_validate_rejects_launch_actions_enabled() -> None:
    """Validation rejects launch_actions_enabled=True."""
    handle = build_observable_artifact_handle_fixture()
    handle["launch_actions_enabled"] = True
    result = validate_observable_artifact_handle(handle)
    assert result["ok"] is False
    assert any("launch_actions" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def test_projection_running_state() -> None:
    """Running state projects poll action."""
    handle = build_observable_artifact_handle_fixture(state="running")
    projection = project_observable_artifact_handle(handle)
    assert projection["first_screen"]["waiting_on"] == "external_system"
    assert projection["first_screen"]["next_safe_action"] == "poll_observable_handle"
    assert projection["first_screen"]["operator_action_required"] is False


def test_projection_completed_state() -> None:
    """Completed state projects ingest closeout."""
    handle = build_observable_artifact_handle_fixture(state="completed")
    projection = project_observable_artifact_handle(handle)
    assert projection["first_screen"]["waiting_on"] == "none"
    assert projection["first_screen"]["next_safe_action"] == "ingest_compact_closeout"


def test_projection_unknown_state() -> None:
    """Unknown state projects operator investigation."""
    handle = build_observable_artifact_handle_fixture(state="unknown")
    projection = project_observable_artifact_handle(handle)
    assert projection["first_screen"]["waiting_on"] == "operator"
    assert projection["first_screen"]["operator_action_required"] is True


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def test_policy_running_allows_poll() -> None:
    """Running state allows polling."""
    handle = build_observable_artifact_handle_fixture(state="running")
    policy = build_observable_artifact_handle_policy(handle)
    assert policy["poll_allowed"] is True
    assert policy["cleanup_required"] is False
    assert policy["next_action"] == "poll_observable_handle"


def test_policy_completed_requires_cleanup() -> None:
    """Completed state requires cleanup."""
    handle = build_observable_artifact_handle_fixture(state="completed")
    policy = build_observable_artifact_handle_policy(handle)
    assert policy["is_terminal"] is True
    assert policy["cleanup_required"] is True
    assert policy["poll_allowed"] is False
    assert "ingest" in policy["next_action"] or "disable" in policy["next_action"]


def test_policy_failed_without_refs() -> None:
    """Failed state without refs disables poll."""
    handle = build_observable_artifact_handle(
        handle_id="failed-no-refs",
        display_name="Failed No Refs",
        state="failed",
    )
    policy = build_observable_artifact_handle_policy(handle)
    assert policy["is_terminal"] is True
    assert "disable_poll" in policy["next_action"]


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def test_render_markdown_includes_key_fields() -> None:
    """Markdown output includes handle_id, state, terminal markers."""
    handle = build_observable_artifact_handle_fixture(state="running")
    markdown = render_observable_artifact_handle_markdown(handle)
    assert "demo-handle-001" in markdown
    assert "running" in markdown
    assert "Observable Artifact Handle" in markdown
    assert "Read Boundary" in markdown


def test_render_markdown_terminal_handle() -> None:
    """Markdown shows terminal=true for completed handles."""
    handle = build_observable_artifact_handle_fixture(state="completed")
    markdown = render_observable_artifact_handle_markdown(handle)
    assert "terminal: `True`" in markdown


# ---------------------------------------------------------------------------
# ObservableArtifactHandle typed model
# ---------------------------------------------------------------------------

def test_typed_handle_as_dict() -> None:
    """Typed handle produces correct as_dict."""
    handle = ObservableArtifactHandle(
        handle_id="typed-1",
        handle_kind=ArtifactHandleKind("benchmark_attempt"),
        display_name="Typed Benchmark",
        state=ArtifactHandleState("running"),
        allowed_poll_command="benchmark poll",
        artifact_refs=("ref1", "ref2"),
    )
    d = handle.as_dict()
    assert d["schema_version"] == "observable_artifact_handle_v0"
    assert d["handle_id"] == "typed-1"
    assert d["handle_kind"] == "benchmark_attempt"
    assert d["is_terminal"] is False
    assert d["artifact_ref_count"] == 2
    assert d["terminal_markers"] == sorted(TERMINAL_MARKERS)


def test_typed_handle_terminal() -> None:
    """Typed handle reports terminal correctly."""
    handle = ObservableArtifactHandle(
        handle_id="done",
        handle_kind=ArtifactHandleKind("generic"),
        display_name="Done Handle",
        state=ArtifactHandleState("completed"),
        allowed_poll_command="poll",
    )
    assert handle.is_terminal is True
    assert "completed" in handle.terminal_marker_set


# ---------------------------------------------------------------------------
# Public/redacted ref helpers
# ---------------------------------------------------------------------------

def test_redacts_private_refs() -> None:
    """Private-looking artifact refs are redacted before storage."""
    from loopx.observable_artifact_handle import _public_or_redacted_ref

    # Safe text stays as alias
    safe = _public_or_redacted_ref("artifacts/result.json", field="test")
    assert safe is not None
    assert safe["kind"] == "alias"
    assert safe["value"] == "artifacts/result.json"
    assert safe["raw_recorded"] is False

    # Unsafe path becomes redacted
    redacted = _public_or_redacted_ref(
        "/Users/alice/secret/results.json", field="test"
    )
    assert redacted is not None
    assert redacted["kind"] == "redacted_ref"
    assert redacted["value"].startswith("redacted:")
    assert redacted["raw_recorded"] is False


# ---------------------------------------------------------------------------
# Enum coverage
# ---------------------------------------------------------------------------

def test_allowed_states_sanity() -> None:
    """Allowed states set is consistent with enum."""
    enum_values = {s.value for s in ArtifactHandleState}
    assert ALLOWED_HANDLE_STATES == frozenset(enum_values)


def test_allowed_kinds_sanity() -> None:
    """Allowed kinds set is consistent with enum."""
    enum_values = {k.value for k in ArtifactHandleKind}
    assert ALLOWED_HANDLE_KINDS == frozenset(enum_values)


def test_terminal_markers_are_subset_of_states() -> None:
    """Every terminal marker is a valid state."""
    assert TERMINAL_MARKERS.issubset(ALLOWED_HANDLE_STATES)
