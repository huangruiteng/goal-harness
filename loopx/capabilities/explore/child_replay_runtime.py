"""Execution engine for optional isolated ReplayPoint child groups."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Sequence

from .replay_runtime import (
    EquivalenceReport,
    ForkReplayChildRequest,
    ReplayChildExecutionContext,
    ReplayChildExecutionFailure,
    ReplayChildExecutionResult,
    ReplayChildFailureStage,
    ReplayChildConcurrency,
    ReplayChildLease,
    ReplayChildTask,
    ReplayFidelity,
    ReplayPointLifecycle,
    ReplayRiskAssessment,
    ReplayRiskDisposition,
    ReplayRiskRejectedError,
    ReplayRestoreResult,
    _validate_equivalence_contract,
    fidelity_meets,
    isolated_replay_child_mode,
    replay_child_risk_mode,
)


def run_child_group_from(
    registry: Any,
    replay_point_id: str,
    tasks: Sequence[ReplayChildTask],
    *,
    parallel: bool = False,
    max_workers: int | None = None,
    settle_failures: bool = False,
) -> tuple[ReplayChildExecutionResult | ReplayChildExecutionFailure, ...]:
    """Run suffixes on isolated child sessions or a safe serial fallback."""

    normalized_tasks = tuple(tasks)
    if not normalized_tasks:
        raise ValueError("run_child_group_from requires at least one task")
    if not all(isinstance(task, ReplayChildTask) for task in normalized_tasks):
        raise TypeError("tasks must contain ReplayChildTask values")
    child_ids = [task.child_id for task in normalized_tasks]
    if len(child_ids) != len(set(child_ids)):
        raise ValueError("ReplayChildTask child_id values must be unique")
    registry._metrics.increment("child_group_attempt_count")
    try:
        with registry._lock:
            try:
                entry = registry._entries[replay_point_id]
            except KeyError as error:
                raise KeyError(f"unknown replay_point_id: {replay_point_id}") from error
            if entry.point.lifecycle != ReplayPointLifecycle.READY:
                raise RuntimeError(
                    "ReplayPoint must be ready before child replay: "
                    f"{entry.point.lifecycle.value}"
                )
            if entry.adapter_binding_key is None:
                raise RuntimeError("replayable ReplayPoint has no Adapter binding")
        child_mode = isolated_replay_child_mode(
            entry.adapter,
            entry.agent_state_store,
        )
        if child_mode is None:
            if settle_failures:
                raise RuntimeError(
                    "settled child results require isolated child sessions"
                )
            registry._metrics.increment("child_serial_fallback_group_count")
            results: list[ReplayChildExecutionResult] = []
            for task in normalized_tasks:
                restore, outcome = registry.run_from(
                    replay_point_id,
                    target_branch_id=task.target_branch_id,
                    minimum_fidelity=task.minimum_fidelity,
                    execute=lambda restored, current=task: current.execute(
                        ReplayChildExecutionContext(
                            child_id=current.child_id,
                            restore=restored,
                            isolated=False,
                            adapter_child_key=None,
                        )
                    ),
                )
                results.append(
                    ReplayChildExecutionResult(
                        child_id=task.child_id,
                        restore=restore,
                        outcome=outcome,
                        isolated=False,
                        parallel=False,
                    )
                )
            registry._metrics.increment("child_group_success_count")
            return tuple(results)

        risk_mode = replay_child_risk_mode(entry.adapter)
        prepared: list[dict[str, Any]] = []
        cleanup_failed = threading.Event()
        unsafe_outcome = threading.Event()

        def cleanup(session: dict[str, Any]) -> Exception | None:
            if session.get("cleanup_attempted"):
                return session.get("cleanup_error")
            session["cleanup_attempted"] = True
            if session["released"]:
                return None
            registry._metrics.increment("child_session_release_attempt_count")
            first_error: Exception | None = None
            child_key = session["lease"].child_key
            try:
                entry.adapter.release_replay_child(child_key)
            except Exception as error:
                first_error = error
            agent_key = session.get("agent_key")
            if agent_key is not None:
                try:
                    entry.agent_state_store.release_agent_state(agent_key)
                except Exception as error:
                    first_error = first_error or error
            session["released"] = first_error is None
            session["cleanup_error"] = first_error
            if first_error is None:
                registry._metrics.increment("child_session_release_success_count")
            else:
                cleanup_failed.set()
                registry._metrics.increment("child_session_release_failure_count")
            return first_error

        with entry.replay_lock:
            with registry._lock:
                if entry.point.lifecycle != ReplayPointLifecycle.READY:
                    raise RuntimeError(
                        "ReplayPoint stopped being ready before child fork: "
                        f"{entry.point.lifecycle.value}"
                    )
            preparation_complete = False
            try:
                for task in normalized_tasks:
                    registry._metrics.increment("child_session_fork_attempt_count")
                    fork_started = time.perf_counter()
                    request = ForkReplayChildRequest(
                        replay_point_id=replay_point_id,
                        child_id=task.child_id,
                        target_branch_id=task.target_branch_id,
                        minimum_fidelity=task.minimum_fidelity,
                    )
                    lease = entry.adapter.fork_replay_child(
                        entry.adapter_binding_key,
                        request,
                    )
                    if not isinstance(lease, ReplayChildLease):
                        raise TypeError(
                            "fork_replay_child must return a ReplayChildLease"
                        )
                    if any(
                        lease.child_key is item["lease"].child_key for item in prepared
                    ):
                        raise ValueError("isolated replay child keys must be unique")
                    session: dict[str, Any] = {
                        "task": task,
                        "lease": lease,
                        "agent_key": None,
                        "released": False,
                        "restore_minutes": (time.perf_counter() - fork_started) / 60.0,
                    }
                    prepared.append(session)
                    agent_key = entry.agent_state_store.fork_agent_state(
                        entry.agent_state_key,
                        task.child_id,
                    )
                    if agent_key is None:
                        raise TypeError(
                            "fork_agent_state must return an opaque child key"
                        )
                    if any(
                        agent_key is item.get("agent_key") for item in prepared[:-1]
                    ):
                        raise ValueError("isolated agent child keys must be unique")
                    session["agent_key"] = agent_key
                    receipt = lease.receipt
                    if receipt.achieved_fidelity == ReplayFidelity.NON_REPLAYABLE:
                        raise RuntimeError("isolated child reported non_replayable")
                    if not fidelity_meets(
                        entry.point.fidelity,
                        receipt.achieved_fidelity,
                    ):
                        raise ValueError(
                            "child restore achieved fidelity stronger than the "
                            "captured ReplayPoint"
                        )
                    equivalence_started = time.perf_counter()
                    report = entry.adapter.validate_replay_child_equivalence(
                        lease.child_key,
                        receipt,
                    )
                    if not isinstance(report, EquivalenceReport):
                        raise TypeError(
                            "validate_replay_child_equivalence must return an "
                            "EquivalenceReport"
                        )
                    promotion_eligible = _validate_equivalence_contract(
                        entry.point,
                        receipt,
                        report,
                        task.minimum_fidelity,
                    )
                    equivalence_minutes = (
                        time.perf_counter() - equivalence_started
                    ) / 60.0
                    registry._metrics.observe_fidelity(report.achieved_fidelity.value)
                    session["context"] = ReplayChildExecutionContext(
                        child_id=task.child_id,
                        restore=ReplayRestoreResult(
                            replay_point_id=replay_point_id,
                            target_branch_id=task.target_branch_id,
                            achieved_fidelity=report.achieved_fidelity,
                            equivalent=report.equivalent,
                            promotion_eligible=promotion_eligible,
                            prefix_reused=receipt.prefix_reused,
                            report=report,
                            restore_minutes=session["restore_minutes"],
                            equivalence_minutes=equivalence_minutes,
                            suffix_minutes=0.0,
                            replay_wall_minutes=0.0,
                        ),
                        isolated=True,
                        adapter_child_key=lease.child_key,
                    )
                    registry._metrics.increment("child_session_fork_success_count")

                preparation_complete = True
                requested_parallel = bool(parallel and len(prepared) > 1)
                process_worker_identities = [
                    session["lease"].worker_identity
                    for session in prepared
                    if session["lease"].concurrency
                    == ReplayChildConcurrency.PROCESS_ISOLATED
                ]
                distinct_process_workers = all(
                    identity is not other
                    for index, identity in enumerate(process_worker_identities)
                    for other in process_worker_identities[:index]
                )
                actual_parallel = bool(
                    requested_parallel
                    and all(
                        session["lease"].concurrency
                        in {
                            ReplayChildConcurrency.THREAD_SAFE,
                            ReplayChildConcurrency.PROCESS_ISOLATED,
                        }
                        for session in prepared
                    )
                    and distinct_process_workers
                )
                if actual_parallel:
                    registry._metrics.increment("child_parallel_group_count")
                    if process_worker_identities:
                        registry._metrics.increment(
                            "child_process_isolated_parallel_group_count"
                        )
                elif requested_parallel:
                    registry._metrics.increment("child_parallel_downgrade_group_count")

                def execute_session(
                    session: dict[str, Any],
                ) -> ReplayChildExecutionResult | ReplayChildExecutionFailure:
                    task = session["task"]
                    context = session["context"]
                    suffix_started = time.perf_counter()
                    execution_error: Exception | None = None
                    outcome: Any = None
                    intent_assessment: ReplayRiskAssessment | None = None
                    outcome_assessment: ReplayRiskAssessment | None = None
                    try:
                        if risk_mode is not None:
                            registry._metrics.increment("child_intent_assessment_count")
                            intent_assessment = (
                                entry.adapter.assess_replay_child_intent(
                                    session["lease"].child_key,
                                    task.intent,
                                )
                            )
                            if not isinstance(
                                intent_assessment,
                                ReplayRiskAssessment,
                            ):
                                raise TypeError(
                                    "assess_replay_child_intent must return a "
                                    "ReplayRiskAssessment"
                                )
                            if (
                                intent_assessment.disposition
                                == ReplayRiskDisposition.DENY
                            ):
                                registry._metrics.increment("child_intent_denied_count")
                                raise ReplayRiskRejectedError(
                                    "intent",
                                    intent_assessment,
                                )
                            registry._metrics.increment("child_intent_allowed_count")
                        entry.agent_state_store.restore_agent_state(
                            session["agent_key"]
                        )
                        outcome = task.execute(context)
                        if risk_mode is not None:
                            registry._metrics.increment(
                                "child_outcome_assessment_count"
                            )
                            outcome_assessment = (
                                entry.adapter.assess_replay_child_outcome(
                                    session["lease"].child_key,
                                    task.intent,
                                    outcome,
                                )
                            )
                            if not isinstance(
                                outcome_assessment,
                                ReplayRiskAssessment,
                            ):
                                raise TypeError(
                                    "assess_replay_child_outcome must return a "
                                    "ReplayRiskAssessment"
                                )
                            if (
                                outcome_assessment.disposition
                                == ReplayRiskDisposition.DENY
                            ):
                                registry._metrics.increment(
                                    "child_outcome_denied_count"
                                )
                                unsafe_outcome.set()
                                raise ReplayRiskRejectedError(
                                    "outcome",
                                    outcome_assessment,
                                )
                            registry._metrics.increment("child_outcome_allowed_count")
                    except Exception as error:
                        execution_error = error
                    suffix_minutes = (time.perf_counter() - suffix_started) / 60.0
                    cleanup_error = cleanup(session)
                    restore = replace(
                        context.restore,
                        suffix_minutes=suffix_minutes,
                        replay_wall_minutes=(
                            context.restore.restore_minutes
                            + context.restore.equivalence_minutes
                            + suffix_minutes
                        ),
                    )
                    if execution_error is not None:
                        if cleanup_error is not None:
                            raise execution_error from cleanup_error
                        if settle_failures and not unsafe_outcome.is_set():
                            risk_error = (
                                execution_error
                                if isinstance(
                                    execution_error,
                                    ReplayRiskRejectedError,
                                )
                                else None
                            )
                            return ReplayChildExecutionFailure(
                                child_id=task.child_id,
                                restore=restore,
                                stage=(
                                    ReplayChildFailureStage.INTENT
                                    if risk_error is not None
                                    and risk_error.stage == "intent"
                                    else ReplayChildFailureStage.SUFFIX
                                ),
                                error_type=type(execution_error).__name__,
                                isolated=True,
                                parallel=actual_parallel,
                                risk_assessment=(
                                    risk_error.assessment
                                    if risk_error is not None
                                    else None
                                ),
                            )
                        raise execution_error
                    if cleanup_error is not None:
                        raise cleanup_error
                    return ReplayChildExecutionResult(
                        child_id=task.child_id,
                        restore=restore,
                        outcome=outcome,
                        isolated=True,
                        parallel=actual_parallel,
                        intent_assessment=intent_assessment,
                        outcome_assessment=outcome_assessment,
                    )

                if actual_parallel:
                    worker_count = max_workers or len(prepared)
                    with ThreadPoolExecutor(
                        max_workers=min(worker_count, len(prepared))
                    ) as executor:
                        futures = [
                            executor.submit(execute_session, session)
                            for session in prepared
                        ]
                        first_error: Exception | None = None
                        results = []
                        for future in futures:
                            try:
                                results.append(future.result())
                            except Exception as error:
                                first_error = first_error or error
                        if first_error is not None:
                            raise first_error
                else:
                    results = [execute_session(session) for session in prepared]
            except Exception as error:
                if not preparation_complete:
                    registry._metrics.increment("child_session_fork_failure_count")
                cleanup_error: Exception | None = None
                for session in prepared:
                    cleanup_error = cleanup(session) or cleanup_error
                if cleanup_failed.is_set() or unsafe_outcome.is_set():
                    with registry._lock:
                        entry.point = replace(
                            entry.point,
                            lifecycle=ReplayPointLifecycle.FAILED,
                        )
                    registry._metrics.increment("replay_point_quarantine_count")
                if (
                    cleanup_error is not None
                    and cleanup_error is not error
                    and error.__cause__ is None
                ):
                    raise error from cleanup_error
                raise
        if settle_failures:
            candidate_failure_count = sum(
                isinstance(result, ReplayChildExecutionFailure) for result in results
            )
            registry._metrics.increment(
                "child_candidate_success_count",
                len(results) - candidate_failure_count,
            )
            registry._metrics.increment(
                "child_candidate_failure_count",
                candidate_failure_count,
            )
            if candidate_failure_count:
                registry._metrics.increment("child_group_settled_count")
            else:
                registry._metrics.increment("child_group_success_count")
        else:
            registry._metrics.increment("child_group_success_count")
        return tuple(results)
    except Exception:
        registry._metrics.increment("child_group_failure_count")
        raise
