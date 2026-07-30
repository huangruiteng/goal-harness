from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .skillsbench_failure_signals import (
    skillsbench_runner_error_fingerprint,
    skillsbench_setup_failure_category,
)


SCHEMA_VERSION = "skillsbench_setup_only_public_preflight_v1"
SCORED_LIFECYCLE_READINESS_GATE_SCHEMA_VERSION = (
    "skillsbench_scored_lifecycle_readiness_gate_v0"
)
MAX_SCORED_LIFECYCLE_TERMINAL_BUDGET_SEC = 300
COMPOSE_TYPED_CAUSE_SCHEMA_VERSION = "skillsbench_compose_typed_cause_v0"
APT_TRANSPORT_RECEIPT_SCHEMA_VERSION = "skillsbench_apt_transport_failure_receipt_v0"
_PATCH_SUFFIX = "_patch_applied"
_PUBLIC_TASK_STAGING_BOOL_FIELDS = (
    "staged",
    "apt_retry_patch_applied",
    "dockerfile_ubuntu_apt_mirror_patch_required",
    "dockerfile_ubuntu_apt_mirror_patch_applied",
    "dockerfile_ubuntu_apt_mirror_raw_url_recorded",
    "dockerfile_debian_apt_mirror_patch_required",
    "dockerfile_debian_apt_mirror_patch_applied",
    "dockerfile_debian_apt_mirror_raw_url_recorded",
    "dockerfile_pip_bootstrap_patch_required",
    "dockerfile_pip_bootstrap_patch_applied",
    "dockerfile_venv_pip_invocation_patch_required",
    "dockerfile_venv_pip_invocation_patch_applied",
    "dockerfile_gcr_mirror_patch_required",
    "dockerfile_gcr_mirror_patch_applied",
    "dockerfile_gcr_mirror_raw_prefix_recorded",
    "dockerfile_wget_gpg_key_retry_patch_required",
    "dockerfile_wget_gpg_key_retry_patch_applied",
    "dockerfile_network_download_retry_patch_required",
    "dockerfile_network_download_retry_patch_applied",
    "dockerfile_uv_bootstrap_mirror_patch_required",
    "dockerfile_uv_bootstrap_mirror_patch_applied",
    "dockerfile_apache_archive_mirror_patch_required",
    "dockerfile_apache_archive_mirror_patch_applied",
    "dockerfile_apache_archive_raw_url_recorded",
    "dockerfile_maven_mirror_patch_required",
    "dockerfile_maven_mirror_patch_applied",
    "dockerfile_maven_mirror_raw_url_recorded",
    "benchmark_egress_proxy_dockerfile_env_patch_required",
    "benchmark_egress_proxy_dockerfile_env_patch_applied",
    "benchmark_egress_proxy_dockerfile_env_raw_proxy_recorded",
    "verifier_uv_bootstrap_mirror_patch_required",
    "verifier_uv_bootstrap_mirror_patch_applied",
    "verifier_dependency_cache_required",
    "verifier_dependency_cache_env_patch_applied",
    "verifier_dependency_cache_raw_path_recorded",
)
_PUBLIC_TASK_STAGING_STRING_FIELDS = (
    "schema_version",
    "dockerfile_apt_source_mode",
    "dockerfile_apt_transport_mode",
    "dockerfile_ubuntu_apt_mirror_host",
    "dockerfile_debian_apt_mirror_host",
    "dockerfile_pip_index_host",
    "dockerfile_pip_build_mode",
    "dockerfile_uv_bootstrap_version",
    "dockerfile_uv_bootstrap_mirror_host",
    "dockerfile_apache_archive_mirror_host",
    "dockerfile_maven_mirror_host",
    "verifier_uv_bootstrap_version",
    "verifier_uv_bootstrap_mirror_host",
)
_COMPOSE_EXCEPTION_FINGERPRINT_TEXT_LIMIT = 64 * 1024
_COMPOSE_EXCEPTION_FINGERPRINT_HEAD_LIMIT = 8 * 1024


class SkillsBenchComposeCommandFailure(RuntimeError):
    """Carry only a bounded public fingerprint beyond the compose producer."""

    def __init__(self, fingerprint: Mapping[str, object]) -> None:
        super().__init__(
            "SkillsBench compose command failed with a bounded typed cause"
        )
        self.schema_version = COMPOSE_TYPED_CAUSE_SCHEMA_VERSION
        self.fingerprint = dict(fingerprint)


def skillsbench_compose_typed_fingerprint(
    exc: Exception,
) -> dict[str, object] | None:
    if not isinstance(exc, SkillsBenchComposeCommandFailure):
        return None
    if exc.schema_version != COMPOSE_TYPED_CAUSE_SCHEMA_VERSION:
        return None
    return dict(exc.fingerprint)


def _compose_exception_fingerprint_text(exc: Exception) -> str:
    """Collect producer-owned output only long enough to derive a fingerprint."""

    parts: list[str] = []
    remaining = _COMPOSE_EXCEPTION_FINGERPRINT_TEXT_LIMIT
    for value in (
        str(exc),
        getattr(exc, "stderr", None),
        getattr(exc, "stdout", None),
        getattr(exc, "output", None),
    ):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if not isinstance(value, str) or not value or remaining <= 0:
            continue
        if len(value) <= remaining:
            part = value
        else:
            head_size = min(
                _COMPOSE_EXCEPTION_FINGERPRINT_HEAD_LIMIT,
                max(0, remaining - 1),
            )
            tail_size = max(0, remaining - head_size - 1)
            if tail_size:
                part = f"{value[:head_size]}\n{value[-tail_size:]}"
            else:
                part = value[:remaining]
        parts.append(part)
        remaining -= len(part) + 1
    return "\n".join(parts)


def install_skillsbench_compose_typed_cause_boundary(
    environment: Any,
) -> Callable[[], None] | None:
    """Type final build failures without changing BenchFlow's retry loop."""

    original_build = getattr(environment, "_run_docker_compose_build", None)
    if not callable(original_build):
        return None

    async def build_with_typed_cause(*args: Any, **kwargs: Any) -> Any:
        try:
            return await original_build(*args, **kwargs)
        except SkillsBenchComposeCommandFailure:
            raise
        except Exception as exc:
            fingerprint = skillsbench_runner_error_fingerprint(
                _compose_exception_fingerprint_text(exc)
            )
            raise SkillsBenchComposeCommandFailure(fingerprint) from None

    try:
        setattr(environment, "_run_docker_compose_build", build_with_typed_cause)
    except (AttributeError, TypeError):
        return None

    def restore() -> None:
        if (
            getattr(environment, "_run_docker_compose_build", None)
            is build_with_typed_cause
        ):
            setattr(environment, "_run_docker_compose_build", original_build)

    return restore


def _patch_hits(task_staging: Mapping[str, Any] | None) -> list[str]:
    staging = task_staging or {}
    return sorted(
        key.removesuffix(_PATCH_SUFFIX)
        for key, value in staging.items()
        if isinstance(key, str) and key.endswith(_PATCH_SUFFIX) and value is True
    )


def _public_task_staging(task_staging: Mapping[str, Any] | None) -> dict[str, Any]:
    staging = task_staging or {}
    public: dict[str, Any] = {}
    for field in _PUBLIC_TASK_STAGING_STRING_FIELDS:
        value = staging.get(field)
        if isinstance(value, str) and value:
            public[field] = value[:180]
    for field in _PUBLIC_TASK_STAGING_BOOL_FIELDS:
        value = staging.get(field)
        if isinstance(value, bool):
            public[field] = value
    return public


def _apt_transport_failure_receipt(
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    dependency_classes = {
        str(item)
        for field in ("dependency_classes", "terminal_dependency_classes")
        for item in result.get(field, [])
        if isinstance(item, str)
    }
    reason_codes = [
        str(item)
        for item in result.get("failure_reason_codes", [])
        if isinstance(item, str)
    ]
    subtype = str(result.get("apt_failure_subtype") or "none")
    apt_failure_present = (
        subtype != "none"
        or "system_package" in dependency_classes
        or any(reason.startswith("apt_") for reason in reason_codes)
    )
    if not apt_failure_present:
        return None

    classification_complete = subtype not in {
        "none",
        "unclassified",
        "fetch_failed_unclassified",
    }
    retryability = str(result.get("retryability") or "unknown")
    if retryability == "retryable" and classification_complete:
        disposition = "bounded_retry_allowed"
    elif retryability == "non_retryable":
        disposition = "repair_before_retry"
    else:
        disposition = "do_not_blind_retry"

    projected_staging = result.get("task_staging")
    staging = projected_staging if isinstance(projected_staging, Mapping) else {}
    transport_configuration = {
        "source_mode": str(staging.get("dockerfile_apt_source_mode") or "unknown"),
        "transport_mode": str(
            staging.get("dockerfile_apt_transport_mode") or "unknown"
        ),
        "apt_retry_patch_applied": (staging.get("apt_retry_patch_applied") is True),
        "proxy_env_patch_required": (
            staging.get("benchmark_egress_proxy_dockerfile_env_patch_required") is True
        ),
        "proxy_env_patch_applied": (
            staging.get("benchmark_egress_proxy_dockerfile_env_patch_applied") is True
        ),
        "ubuntu_mirror_patch_required": (
            staging.get("dockerfile_ubuntu_apt_mirror_patch_required") is True
        ),
        "ubuntu_mirror_patch_applied": (
            staging.get("dockerfile_ubuntu_apt_mirror_patch_applied") is True
        ),
        "debian_mirror_patch_required": (
            staging.get("dockerfile_debian_apt_mirror_patch_required") is True
        ),
        "debian_mirror_patch_applied": (
            staging.get("dockerfile_debian_apt_mirror_patch_applied") is True
        ),
    }
    return {
        "schema_version": APT_TRANSPORT_RECEIPT_SCHEMA_VERSION,
        "classification_status": (
            "classified_transport_failure"
            if classification_complete
            else "unclassified_transport_failure"
        ),
        "classification_complete": classification_complete,
        "failure_subtype": subtype,
        "retryability": retryability,
        "failure_cause_source": str(result.get("failure_cause_source") or "none"),
        "failure_reason_codes": reason_codes,
        "terminal_failure_reason_codes": [
            str(item)
            for item in result.get("terminal_failure_reason_codes", [])
            if isinstance(item, str)
        ],
        "dependency_endpoints": [
            str(item)
            for item in result.get("dependency_endpoints", [])
            if isinstance(item, str)
        ],
        "terminal_dependency_endpoints": [
            str(item)
            for item in result.get("terminal_dependency_endpoints", [])
            if isinstance(item, str)
        ],
        "transport_configuration": transport_configuration,
        "disposition": disposition,
        "raw_failure_text_recorded": False,
        "raw_logs_recorded": False,
        "raw_task_text_recorded": False,
        "raw_verifier_output_recorded": False,
        "host_paths_recorded": False,
        "secret_values_recorded": False,
    }


def _exit_category(exc: Exception, matched_patterns: set[str]) -> str:
    if (
        isinstance(exc, (asyncio.TimeoutError, TimeoutError))
        or "timeout" in matched_patterns
    ):
        return "timeout"
    if isinstance(exc, PermissionError) or "permission_denied" in matched_patterns:
        return "permission_denied"
    if {
        "docker_daemon_unavailable",
        "docker_api_version_mismatch",
        "docker_compose_plugin_unavailable",
    } & matched_patterns:
        return "runtime_unavailable"
    if {
        "docker_compose_command_failed",
        "image_build",
        "apt_failure",
        "pip_bootstrap_failure",
        "volume_mount_failure",
    } & matched_patterns:
        return "setup_command_failed"
    if isinstance(exc, FileNotFoundError) or "missing_file" in matched_patterns:
        return "missing_input"
    return "exception"


def _base_result(
    *,
    task_staging: Mapping[str, Any] | None,
    setup_preflight: Mapping[str, Any] | None,
) -> dict[str, Any]:
    setup = setup_preflight or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "stage": "rollout_create",
        "job_root_materialized": False,
        "environment_object_materialized": False,
        "environment_started": False,
        "environment_ready_hook_requested": False,
        "environment_ready_hook_invoked": False,
        "environment_ready_hook_status": "not_requested",
        "agent_install_canary_requested": False,
        "agent_install_canary_status": "not_requested",
        "agent_install_invoked": False,
        "scored_lifecycle_canary_requested": False,
        "scored_lifecycle_canary_status": "not_requested",
        "scored_lifecycle_terminal_budget_sec": 0,
        "case_goal_state_initialized_before_agent": False,
        "acp_session_initialized": False,
        "agent_active_observed": False,
        "loopx_state_read_count": 0,
        "loopx_state_write_count": 0,
        "task_prompt_sent": False,
        "benchmark_task_launched": False,
        "scored_launch_allowed": False,
        "scored_launch_blocker": "scored_lifecycle_canary_not_requested",
        "loopx_runner_source_git_head": "",
        "loopx_runner_source_expected_git_head": "",
        "loopx_runner_source_matches_expected": False,
        "agent_execution_invoked": False,
        "verifier_invoked": False,
        "dependency_classes": [],
        "terminal_dependency_classes": [],
        "failure_reason_codes": [],
        "terminal_failure_reason_codes": [],
        "apt_failure_subtype": "none",
        "pip_failure_subtype": "none",
        "dependency_endpoints": [],
        "terminal_dependency_endpoints": [],
        "retryability": "unknown",
        "failure_category": "none",
        "exit_category": "pending",
        "failure_cause_source": "none",
        "compose_typed_cause_boundary_installed": False,
        "compose_typed_cause_boundary_restored": False,
        "patch_hits": _patch_hits(task_staging),
        "task_staging": _public_task_staging(task_staging),
        "apt_setup_risk_detected": setup.get("apt_setup_risk_detected") is True,
        "dockerfile_pip_install_risk_detected": (
            setup.get("dockerfile_pip_install_risk_detected") is True
        ),
        "verifier_bootstrap_risk_detected": (
            setup.get("verifier_bootstrap_risk_detected") is True
        ),
        "cleanup_status": "not_started",
        "raw_error_recorded": False,
        "raw_logs_read": False,
        "raw_logs_recorded": False,
        "raw_command_output_recorded": False,
        "raw_task_text_read": False,
        "raw_trajectory_read": False,
        "raw_verifier_output_read": False,
        "host_paths_recorded": False,
        "secret_values_recorded": False,
    }


def skillsbench_scored_lifecycle_readiness_gate(
    receipt: Mapping[str, Any],
    *,
    expected_git_head: str,
) -> dict[str, Any]:
    """Validate the public task-free receipt required before scored launch."""

    expected = str(expected_git_head or "").strip()
    observed = str(receipt.get("loopx_runner_source_git_head") or "").strip()
    blockers: list[str] = []
    read_count = receipt.get("loopx_state_read_count")
    write_count = receipt.get("loopx_state_write_count")
    terminal_budget = receipt.get("scored_lifecycle_terminal_budget_sec")
    required = (
        (
            receipt.get("schema_version") == SCHEMA_VERSION,
            "receipt_schema_mismatch",
        ),
        (receipt.get("status") == "passed", "preflight_not_passed"),
        (
            receipt.get("cleanup_status") == "completed",
            "preflight_cleanup_incomplete",
        ),
        (
            receipt.get("scored_lifecycle_canary_status") == "passed",
            "scored_lifecycle_canary_not_passed",
        ),
        (
            isinstance(terminal_budget, int)
            and not isinstance(terminal_budget, bool)
            and 1 <= terminal_budget <= MAX_SCORED_LIFECYCLE_TERMINAL_BUDGET_SEC,
            "scored_lifecycle_terminal_budget_invalid",
        ),
        (
            receipt.get("case_goal_state_initialized_before_agent") is True,
            "case_state_seed_not_observed",
        ),
        (
            receipt.get("acp_session_initialized") is True,
            "acp_session_not_initialized",
        ),
        (
            receipt.get("agent_active_observed") is True,
            "agent_active_not_observed",
        ),
        (
            isinstance(read_count, int)
            and not isinstance(read_count, bool)
            and read_count >= 1,
            "loopx_state_read_not_observed",
        ),
        (
            isinstance(write_count, int)
            and not isinstance(write_count, bool)
            and write_count >= 1,
            "loopx_state_write_not_observed",
        ),
        (
            receipt.get("task_prompt_sent") is False,
            "task_prompt_boundary_not_proven",
        ),
        (
            receipt.get("benchmark_task_launched") is False,
            "benchmark_task_boundary_not_proven",
        ),
        (
            receipt.get("agent_execution_invoked") is False,
            "agent_execution_boundary_not_proven",
        ),
        (
            receipt.get("verifier_invoked") is False,
            "verifier_boundary_not_proven",
        ),
        (
            receipt.get("scored_launch_allowed") is True,
            "receipt_does_not_allow_scored_launch",
        ),
    )
    blockers.extend(reason for passed, reason in required if not passed)
    if not expected:
        blockers.append("expected_loopx_git_head_missing")
    elif not observed or not observed.startswith(expected):
        blockers.append("loopx_runner_source_git_head_mismatch")
    if receipt.get("loopx_runner_source_matches_expected") is not True:
        blockers.append("loopx_runner_source_match_not_proven")

    return {
        "schema_version": SCORED_LIFECYCLE_READINESS_GATE_SCHEMA_VERSION,
        "allowed": not blockers,
        "blockers": blockers,
        "expected_git_head": expected[:40],
        "observed_git_head": observed[:40],
        "raw_logs_read": False,
        "raw_task_text_read": False,
        "raw_trajectory_read": False,
        "raw_verifier_output_read": False,
        "host_paths_recorded": False,
        "secret_values_recorded": False,
    }


def _emit_progress(
    callback: Callable[[Mapping[str, Any]], None] | None,
    result: Mapping[str, Any],
) -> None:
    if callback is not None:
        callback(dict(result))


async def run_setup_only_public_preflight(
    *,
    rollout_type: Any,
    config: Any,
    task_staging: Mapping[str, Any] | None = None,
    setup_preflight: Mapping[str, Any] | None = None,
    stage_timeout_sec: float,
    cleanup_timeout_sec: float = 30.0,
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
    environment_ready_hook: Callable[[Any], Awaitable[None]] | None = None,
    agent_install_canary: bool = False,
    scored_lifecycle_canary: (
        Callable[[Any], Awaitable[Mapping[str, Any]]] | None
    ) = None,
    scored_lifecycle_timeout_sec: float = 180.0,
) -> dict[str, Any]:
    """Materialize a BenchFlow environment and optionally canary scored readiness."""

    result = _base_result(
        task_staging=task_staging,
        setup_preflight=setup_preflight,
    )
    stage_timeout_sec = max(1.0, stage_timeout_sec)
    cleanup_timeout_sec = max(1.0, cleanup_timeout_sec)
    scored_lifecycle_timeout_sec = max(0.01, scored_lifecycle_timeout_sec)
    rollout: Any | None = None
    restore_compose_boundary: Callable[[], None] | None = None
    scored_lifecycle_started_at: float | None = None
    failed = False
    if environment_ready_hook is not None:
        result["environment_ready_hook_requested"] = True
        result["environment_ready_hook_status"] = "pending"
    if agent_install_canary:
        result["agent_install_canary_requested"] = True
        result["agent_install_canary_status"] = "pending"
    if scored_lifecycle_canary is not None:
        if not agent_install_canary:
            raise ValueError("scored lifecycle canary requires agent install canary")
        result["scored_lifecycle_canary_requested"] = True
        result["scored_lifecycle_canary_status"] = "pending"
        result["scored_lifecycle_terminal_budget_sec"] = int(
            scored_lifecycle_timeout_sec
        )
        result["scored_launch_blocker"] = "scored_lifecycle_canary_not_passed"
    _emit_progress(progress_callback, result)
    try:
        rollout = await asyncio.wait_for(
            rollout_type.create(config),
            timeout=stage_timeout_sec,
        )
        result["stage"] = "rollout_setup"
        _emit_progress(progress_callback, result)
        await asyncio.wait_for(rollout.setup(), timeout=stage_timeout_sec)
        result["job_root_materialized"] = (
            getattr(rollout, "_rollout_dir", None) is not None
        )
        result["environment_object_materialized"] = (
            getattr(rollout, "env", None) is not None
        )

        restore_compose_boundary = install_skillsbench_compose_typed_cause_boundary(
            getattr(rollout, "env", None)
        )
        result["compose_typed_cause_boundary_installed"] = (
            restore_compose_boundary is not None
        )

        result["stage"] = "environment_start"
        _emit_progress(progress_callback, result)
        await asyncio.wait_for(rollout.start(), timeout=stage_timeout_sec)
        result["environment_started"] = True
        if environment_ready_hook is not None:
            result["stage"] = "environment_ready_hook"
            result["environment_ready_hook_invoked"] = True
            result["environment_ready_hook_status"] = "running"
            _emit_progress(progress_callback, result)
            await asyncio.wait_for(
                environment_ready_hook(getattr(rollout, "env", None)),
                timeout=stage_timeout_sec,
            )
            result["environment_ready_hook_status"] = "passed"
        if agent_install_canary:
            scored_lifecycle_started_at = (
                asyncio.get_running_loop().time()
                if scored_lifecycle_canary is not None
                else None
            )
            result["stage"] = "agent_install_canary"
            result["agent_install_invoked"] = True
            result["agent_install_canary_status"] = "running"
            _emit_progress(progress_callback, result)
            await asyncio.wait_for(
                rollout.install_agent(),
                timeout=(
                    scored_lifecycle_timeout_sec
                    if scored_lifecycle_canary is not None
                    else stage_timeout_sec
                ),
            )
            result["agent_install_canary_status"] = "passed"
        if scored_lifecycle_canary is not None:
            if scored_lifecycle_started_at is None:
                raise RuntimeError("scored lifecycle canary budget did not start")
            result["stage"] = "scored_lifecycle_canary"
            result["scored_lifecycle_canary_status"] = "running"
            _emit_progress(progress_callback, result)
            remaining_timeout_sec = max(
                0.001,
                scored_lifecycle_timeout_sec
                - (
                    asyncio.get_running_loop().time()
                    - scored_lifecycle_started_at
                ),
            )
            lifecycle = await asyncio.wait_for(
                scored_lifecycle_canary(rollout),
                timeout=remaining_timeout_sec,
            )
            for field in (
                "case_goal_state_initialized_before_agent",
                "acp_session_initialized",
                "agent_active_observed",
                "task_prompt_sent",
                "benchmark_task_launched",
                "loopx_runner_source_matches_expected",
            ):
                result[field] = lifecycle.get(field) is True
            for field in ("loopx_state_read_count", "loopx_state_write_count"):
                value = lifecycle.get(field)
                result[field] = (
                    max(0, int(value))
                    if isinstance(value, int) and not isinstance(value, bool)
                    else 0
                )
            for field in (
                "loopx_runner_source_git_head",
                "loopx_runner_source_expected_git_head",
            ):
                value = lifecycle.get(field)
                result[field] = str(value or "")[:40]
            readiness = skillsbench_scored_lifecycle_readiness_gate(
                {
                    **result,
                    "status": "passed",
                    "cleanup_status": "completed",
                    "scored_lifecycle_canary_status": "passed",
                    "scored_launch_allowed": True,
                },
                expected_git_head=result[
                    "loopx_runner_source_expected_git_head"
                ],
            )
            if readiness["allowed"] is not True:
                raise RuntimeError("scored lifecycle canary did not prove readiness")
            result["scored_lifecycle_canary_status"] = "passed"
            result["scored_launch_allowed"] = True
            result["scored_launch_blocker"] = "none"
        result["status"] = "passed"
        result["stage"] = (
            "scored_runtime_ready"
            if scored_lifecycle_canary is not None
            else (
                "agent_install_ready_before_execution"
                if agent_install_canary
                else "environment_ready_before_agent"
            )
        )
        result["exit_category"] = "passed"
    except Exception as exc:
        failed = True
        if result["environment_ready_hook_status"] == "running":
            result["environment_ready_hook_status"] = "failed"
        if result["agent_install_canary_status"] == "running":
            result["agent_install_canary_status"] = "failed"
        if result["scored_lifecycle_canary_status"] == "running":
            result["scored_lifecycle_canary_status"] = "failed"
        elif (
            result["scored_lifecycle_canary_requested"] is True
            and result["scored_lifecycle_canary_status"] == "pending"
        ):
            result["scored_lifecycle_canary_status"] = "blocked_before_start"
        result["scored_launch_allowed"] = False
        result["scored_launch_blocker"] = "scored_lifecycle_canary_not_passed"
        if rollout is not None:
            result["job_root_materialized"] = (
                getattr(rollout, "_rollout_dir", None) is not None
            )
            result["environment_object_materialized"] = (
                getattr(rollout, "env", None) is not None
            )
        typed_fingerprint = skillsbench_compose_typed_fingerprint(exc)
        if typed_fingerprint is None:
            fingerprint = skillsbench_runner_error_fingerprint(str(exc))
            result["failure_cause_source"] = "exception_text_fingerprint"
        else:
            fingerprint = typed_fingerprint
            result["failure_cause_source"] = "compose_producer_typed_cause"
        matched_patterns = {
            str(item)
            for item in fingerprint.get("matched_patterns", [])
            if isinstance(item, str)
        }
        result["status"] = "failed"
        result["failure_stage"] = result["stage"]
        result["failure_category"] = skillsbench_setup_failure_category(fingerprint)
        result["exit_category"] = _exit_category(exc, matched_patterns)
        result["dependency_classes"] = [
            str(item)
            for item in fingerprint.get("failure_line_dependency_classes", [])
            if isinstance(item, str)
        ]
        result["terminal_dependency_classes"] = [
            str(item)
            for item in fingerprint.get("terminal_failure_dependency_classes", [])
            if isinstance(item, str)
        ]
        result["failure_reason_codes"] = [
            str(item)
            for item in fingerprint.get("failure_reason_codes", [])
            if isinstance(item, str)
        ]
        result["terminal_failure_reason_codes"] = [
            str(item)
            for item in fingerprint.get("terminal_failure_reason_codes", [])
            if isinstance(item, str)
        ]
        result["apt_failure_subtype"] = str(
            fingerprint.get("apt_failure_subtype") or "none"
        )
        result["pip_failure_subtype"] = str(
            fingerprint.get("pip_failure_subtype") or "none"
        )
        result["dependency_endpoints"] = [
            str(item)
            for item in fingerprint.get("failure_dependency_endpoints", [])
            if isinstance(item, str)
        ]
        result["terminal_dependency_endpoints"] = [
            str(item)
            for item in fingerprint.get("terminal_failure_dependency_endpoints", [])
            if isinstance(item, str)
        ]
        result["retryability"] = str(fingerprint.get("retryability") or "unknown")
        result["fingerprint_patterns"] = sorted(matched_patterns)
        result["fingerprint_confidence"] = str(
            fingerprint.get("fingerprint_confidence")
            or "coarse_public_safe_pattern_match"
        )
        apt_transport_receipt = _apt_transport_failure_receipt(result)
        if apt_transport_receipt is not None:
            result["apt_transport_failure_receipt"] = apt_transport_receipt
    finally:
        if restore_compose_boundary is not None:
            restore_compose_boundary()
            result["compose_typed_cause_boundary_restored"] = True
        if rollout is not None:
            try:
                await asyncio.wait_for(
                    rollout.cleanup(),
                    timeout=cleanup_timeout_sec,
                )
                result["cleanup_status"] = "completed"
            except Exception:
                result["cleanup_status"] = "failed"
                result["scored_launch_allowed"] = False
                result["scored_launch_blocker"] = "preflight_cleanup_incomplete"
                if not failed:
                    result["status"] = "failed"
                    result["failure_stage"] = "cleanup"
                    result["failure_category"] = "skillsbench_setup_cleanup_failure"
                    result["exit_category"] = "cleanup_failed"
        else:
            result["cleanup_status"] = "not_required"
        _emit_progress(progress_callback, result)
    return result
