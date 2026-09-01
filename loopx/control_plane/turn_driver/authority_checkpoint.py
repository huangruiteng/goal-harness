"""Optional authority checkpoints around one governed LoopX Turn.

The Turn driver does not choose or implement a coordination provider here.
Compositions may inject a guard that admits one authority binding before Host
execution and revalidates that exact binding before each durable effect.  The
guard is disabled by default, so the existing local Turn path is unchanged.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...authority import validate_public_safe_text
from .driver import selected_turn_todo
from .settlement import (
    completion_writeback_outcome,
    invoke_result_effect,
    invoke_turn_effect,
    terminal_closeout_requirement,
    verified_terminal_closeout_effect,
)
from .transaction import LoopXTurnResultKind


TURN_AUTHORITY_BINDING_SCHEMA_VERSION = "loopx_turn_authority_binding_v0"
TURN_AUTHORITY_CHECKPOINT_REQUEST_SCHEMA_VERSION = (
    "loopx_turn_authority_checkpoint_request_v0"
)
TURN_AUTHORITY_CHECKPOINT_RECEIPT_SCHEMA_VERSION = (
    "loopx_turn_authority_checkpoint_receipt_v0"
)
TURN_AUTHORITY_CHECKPOINT_JOURNAL_SCHEMA_VERSION = (
    "loopx_turn_authority_checkpoint_journal_v0"
)
TURN_AUTHORITY_CHECKPOINTS = frozenset(
    {
        "host_admission",
        "durable_writeback",
        "quota_spend",
        "authority_complete",
        "terminal_closeout",
        "scheduler",
    }
)

_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "store_identity",
        "operation_id",
        "receipt_digest",
        "authority_revision",
        "todo_revision",
        "lease_id",
        "lease_epoch",
        "expires_at",
    }
)
_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z"
)

TurnAuthorityCheckpointGuard = Callable[[Mapping[str, Any]], Mapping[str, Any]]
PersistCheckpoint = Callable[[], None]
TurnResultEffect = Callable[..., Mapping[str, Any]]
TurnEffect = Callable[..., Mapping[str, Any]]
TurnScheduler = Callable[[dict[str, Any]], dict[str, Any]]
TurnTerminalCheckpoint = Callable[[Mapping[str, Any]], None]
TurnAdmissionFailure = Callable[[str], Mapping[str, Any]]


def build_turn_authority_command_guard(
    argv: Sequence[str],
    *,
    project: Path,
    timeout_seconds: float,
) -> TurnAuthorityCheckpointGuard:
    """Adapt one argv-only TEST ONLY command to the checkpoint contract.

    The command receives exactly one request JSON object on stdin and must emit
    exactly one result JSON object on stdout.  Process and decoding failures are
    deliberately collapsed into one public typed rejection; stderr and local
    provider details never become Turn journal material.
    """

    normalized = tuple(argv)
    if not normalized or not all(isinstance(item, str) and item for item in normalized):
        raise ValueError("Turn authority guard command must be a non-empty argv array")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
    ):
        raise ValueError("Turn authority guard timeout must be positive")

    def reject() -> dict[str, Any]:
        return {
            "ok": False,
            "reason_code": "authority_guard_unavailable",
            "reason": "Turn authority guard command did not return a valid receipt",
        }

    def guard(request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            completed = subprocess.run(
                normalized,
                cwd=project,
                input=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return reject()
        if (
            completed.returncode != 0
            or len(completed.stdout.encode("utf-8")) > 64 * 1024
        ):
            return reject()
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return reject()
        return dict(value) if isinstance(value, Mapping) else reject()

    return guard


def _bounded_public_string(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"authority {field} must be a non-empty trimmed string")
    if len(value) > limit:
        raise ValueError(f"authority {field} exceeds {limit} characters")
    validate_public_safe_text(f"turn_authority.{field}", value)
    return value


def _normalize_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _BINDING_FIELDS:
        raise ValueError("authority binding fields do not match the v0 contract")
    binding = dict(value)
    if binding.get("schema_version") != TURN_AUTHORITY_BINDING_SCHEMA_VERSION:
        raise ValueError("authority binding schema is unsupported")
    for field, limit in (
        ("store_identity", 240),
        ("operation_id", 240),
        ("lease_id", 240),
        ("expires_at", 80),
    ):
        binding[field] = _bounded_public_string(
            binding.get(field), field=field, limit=limit
        )
    if not _TIMESTAMP_RE.fullmatch(binding["expires_at"]):
        raise ValueError("authority expires_at must be a UTC millisecond timestamp")
    digest = _bounded_public_string(
        binding.get("receipt_digest"), field="receipt_digest", limit=71
    )
    if not _DIGEST_RE.fullmatch(digest):
        raise ValueError("authority receipt_digest must use sha256:<64 lowercase hex>")
    binding["receipt_digest"] = digest
    for field, minimum in (
        ("authority_revision", 0),
        ("todo_revision", 0),
        ("lease_epoch", 1),
    ):
        item = binding.get(field)
        if type(item) is not int or item < minimum:
            raise ValueError(f"authority {field} must be an integer >= {minimum}")
    return binding


def _normalize_rejection(value: Mapping[str, Any]) -> tuple[str, str]:
    if set(value) != {"ok", "reason_code", "reason"} or value.get("ok") is not False:
        raise ValueError(
            "authority guard rejection fields do not match the v0 contract"
        )
    reason_code = str(value.get("reason_code") or "")
    if not _REASON_CODE_RE.fullmatch(reason_code):
        raise ValueError("authority guard reason_code is invalid")
    reason = _bounded_public_string(value.get("reason"), field="reason", limit=240)
    return reason_code, reason


def _normalize_completion(
    value: Mapping[str, Any] | None,
    *,
    expected_todo_id: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("authority completion context is missing")
    continuation = value.get("continuation")
    required = {"todo_id", "continuation"}
    if continuation == "successor":
        required.add("successor_todo_ids")
    if set(value) != required or value.get("todo_id") != expected_todo_id:
        raise ValueError("authority completion context does not match the Turn Todo")
    if continuation not in {"active_goal", "no_followup", "successor"}:
        raise ValueError("authority completion continuation is invalid")
    completion = {
        "todo_id": expected_todo_id,
        "continuation": continuation,
    }
    if continuation == "successor":
        successors = value.get("successor_todo_ids")
        if (
            not isinstance(successors, list)
            or not successors
            or not all(isinstance(item, str) and item for item in successors)
            or len(set(successors)) != len(successors)
        ):
            raise ValueError("authority completion successor Todo ids are invalid")
        completion["successor_todo_ids"] = list(successors)
    return completion


@dataclass(frozen=True, slots=True)
class TurnAuthorityCheckpointOutcome:
    accepted: bool
    receipt: dict[str, Any]
    binding: dict[str, Any] | None

    def rejected_effect(self) -> dict[str, Any]:
        return {
            "ok": False,
            "appended": False,
            "reason": str(
                self.receipt.get("reason") or "authority checkpoint rejected"
            ),
            "authority_checkpoint": self.receipt["checkpoint"],
            "authority_reason_code": self.receipt.get("reason_code"),
        }


class TurnAuthorityCheckpointSession:
    """Validate and journal one injected guard without owning its decisions."""

    def __init__(
        self,
        guard: TurnAuthorityCheckpointGuard,
        *,
        goal_id: str,
        agent_id: str,
        todo_id: str,
        turn_key: str,
        effect_id: str,
        journal: dict[str, Any],
        persist: PersistCheckpoint,
    ) -> None:
        self._guard = guard
        self._identity = {
            "goal_id": _bounded_public_string(goal_id, field="goal_id", limit=200),
            "agent_id": _bounded_public_string(agent_id, field="agent_id", limit=200),
            "todo_id": _bounded_public_string(todo_id, field="todo_id", limit=200),
            "turn_key": _bounded_public_string(turn_key, field="turn_key", limit=80),
            "effect_id": _bounded_public_string(
                effect_id, field="effect_id", limit=512
            ),
        }
        self._journal = journal
        self._persist = persist

    @property
    def effect_id(self) -> str:
        return self._identity["effect_id"]

    @property
    def identity(self) -> dict[str, str]:
        """Return the public Turn identity supplied to every checkpoint."""

        return dict(self._identity)

    def _state(self) -> dict[str, Any]:
        value = self._journal.get("authority_checkpoint_guard")
        if value is None:
            value = {
                "schema_version": TURN_AUTHORITY_CHECKPOINT_JOURNAL_SCHEMA_VERSION,
                "checkpoints": {},
            }
            self._journal["authority_checkpoint_guard"] = value
        allowed_fields = {
            "schema_version",
            "checkpoints",
            "binding",
            "invalid_prior_state",
        }
        if (
            not isinstance(value, dict)
            or not set(value).issubset(allowed_fields)
            or value.get("schema_version")
            != TURN_AUTHORITY_CHECKPOINT_JOURNAL_SCHEMA_VERSION
            or not isinstance(value.get("checkpoints"), dict)
            or (
                "invalid_prior_state" in value
                and value.get("invalid_prior_state") is not True
            )
        ):
            raise ValueError("Turn authority checkpoint journal is invalid")
        for checkpoint, receipt in value["checkpoints"].items():
            if checkpoint not in TURN_AUTHORITY_CHECKPOINTS or not isinstance(
                receipt, Mapping
            ):
                raise ValueError("Turn authority checkpoint journal is invalid")
            status = receipt.get("status")
            required = {"schema_version", "checkpoint", "status", "attempt"}
            if "effect_ref" in receipt:
                required.add("effect_ref")
            if status == "rejected":
                required.update({"reason_code", "reason"})
            if (
                set(receipt) != required
                or receipt.get("schema_version")
                != TURN_AUTHORITY_CHECKPOINT_RECEIPT_SCHEMA_VERSION
                or receipt.get("checkpoint") != checkpoint
                or status not in {"accepted", "rejected"}
                or type(receipt.get("attempt")) is not int
                or receipt["attempt"] < 1
            ):
                raise ValueError("Turn authority checkpoint journal is invalid")
            if "effect_ref" in receipt:
                _bounded_public_string(
                    receipt.get("effect_ref"), field="effect_ref", limit=512
                )
            if status == "rejected":
                reason_code = receipt.get("reason_code")
                if not isinstance(reason_code, str) or not _REASON_CODE_RE.fullmatch(
                    reason_code
                ):
                    raise ValueError("Turn authority checkpoint journal is invalid")
                _bounded_public_string(receipt.get("reason"), field="reason", limit=240)
        return value

    def _current_binding(self, state: Mapping[str, Any]) -> dict[str, Any] | None:
        value = state.get("binding")
        return None if value is None else _normalize_binding(value)

    def _record(
        self,
        *,
        checkpoint: str,
        effect_ref: str | None,
        accepted: bool,
        binding: dict[str, Any] | None,
        reason_code: str | None = None,
        reason: str | None = None,
    ) -> TurnAuthorityCheckpointOutcome:
        state = self._state()
        checkpoints = state["checkpoints"]
        assert isinstance(checkpoints, dict)
        previous = checkpoints.get(checkpoint)
        attempt = (
            int(previous.get("attempt") or 0) + 1
            if isinstance(previous, Mapping)
            else 1
        )
        receipt: dict[str, Any] = {
            "schema_version": TURN_AUTHORITY_CHECKPOINT_RECEIPT_SCHEMA_VERSION,
            "checkpoint": checkpoint,
            "status": "accepted" if accepted else "rejected",
            "attempt": attempt,
        }
        if effect_ref is not None:
            receipt["effect_ref"] = effect_ref
        if not accepted:
            receipt.update(reason_code=reason_code, reason=reason)
        checkpoints[checkpoint] = receipt
        if binding is not None:
            state["binding"] = binding
        self._persist()
        return TurnAuthorityCheckpointOutcome(accepted, receipt, binding)

    def checkpoint(
        self,
        checkpoint: str,
        *,
        effect_ref: str | None = None,
        completion: Mapping[str, Any] | None = None,
    ) -> TurnAuthorityCheckpointOutcome:
        if checkpoint not in TURN_AUTHORITY_CHECKPOINTS:
            raise ValueError(f"unsupported Turn authority checkpoint: {checkpoint}")
        if checkpoint == "authority_complete":
            completion_context = _normalize_completion(
                completion,
                expected_todo_id=self._identity["todo_id"],
            )
        elif completion is not None:
            raise ValueError("completion context is only valid at authority_complete")
        else:
            completion_context = None
        try:
            state = self._state()
            current = self._current_binding(state)
        except (TypeError, ValueError) as exc:
            self._journal["authority_checkpoint_guard"] = {
                "schema_version": TURN_AUTHORITY_CHECKPOINT_JOURNAL_SCHEMA_VERSION,
                "checkpoints": {},
                "invalid_prior_state": True,
            }
            return self._record(
                checkpoint=checkpoint,
                effect_ref=effect_ref,
                accepted=False,
                binding=None,
                reason_code="authority_journal_invalid",
                reason=str(exc),
            )
        if checkpoint != "host_admission" and current is None:
            return self._record(
                checkpoint=checkpoint,
                effect_ref=effect_ref,
                accepted=False,
                binding=None,
                reason_code="authority_admission_missing",
                reason="Turn has no accepted authority admission binding",
            )
        request = {
            "schema_version": TURN_AUTHORITY_CHECKPOINT_REQUEST_SCHEMA_VERSION,
            "checkpoint": checkpoint,
            **self._identity,
            "effect_ref": effect_ref,
            "authority_binding": current,
        }
        if completion_context is not None:
            request["completion"] = completion_context
        try:
            raw = self._guard(request)
            if not isinstance(raw, Mapping):
                raise ValueError("authority guard result must be an object")
            result = dict(raw)
            if result.get("ok") is True and set(result) == {"ok", "binding"}:
                binding = _normalize_binding(result.get("binding"))
                if current is not None and binding != current:
                    return self._record(
                        checkpoint=checkpoint,
                        effect_ref=effect_ref,
                        accepted=False,
                        binding=current,
                        reason_code="authority_binding_changed",
                        reason="authority checkpoint returned a different admission binding",
                    )
                return self._record(
                    checkpoint=checkpoint,
                    effect_ref=effect_ref,
                    accepted=True,
                    binding=binding,
                )
            reason_code, reason = _normalize_rejection(result)
        except Exception as exc:  # noqa: BLE001 - injected provider boundary
            reason_code = "authority_guard_invalid"
            reason = f"authority checkpoint guard failed with {type(exc).__name__}"
        return self._record(
            checkpoint=checkpoint,
            effect_ref=effect_ref,
            accepted=False,
            binding=current,
            reason_code=reason_code,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class TurnAuthoritySettlementEffects:
    """Authority-aware callbacks handed to the typed settlement driver."""

    writeback: TurnEffect
    spend: TurnEffect
    terminal_closeout: TurnEffect | None
    terminal_checkpoint: TurnTerminalCheckpoint | None
    terminal_closeout_required: bool


class TurnAuthorityCheckpointController:
    """Keep one Turn's authority checkpoints adjacent to governed effects."""

    def __init__(
        self,
        session: TurnAuthorityCheckpointSession | None,
        *,
        plan: Mapping[str, Any],
        journal: dict[str, Any],
        persist: PersistCheckpoint,
    ) -> None:
        self._session = session
        self._plan = plan
        self._journal = journal
        self._persist = persist

    @property
    def enabled(self) -> bool:
        return self._session is not None

    def admit_host(
        self,
        *,
        completed_phases: Sequence[str],
        failure: TurnAdmissionFailure,
    ) -> bool:
        """Admit Host before its first effect and persist a typed rejection."""

        if self._session is None or "typed_result" in completed_phases:
            return True
        admission = self._session.checkpoint(
            "host_admission",
            effect_ref=self._session.effect_id,
        )
        if admission.accepted:
            return True
        reason = str(admission.receipt.get("reason") or "authority admission rejected")
        rejected = failure(reason)
        self._journal.update(
            status="failed",
            reason=rejected["reason"],
            receipt=rejected["receipt"],
            completed_phases=[],
            result_kind=LoopXTurnResultKind.AUTHORITY_REJECTED.value,
        )
        self._persist()
        return False

    def _rejected_effect(
        self,
        checkpoint: str,
        *,
        effect_ref: str,
        completion: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self._session is None:
            return None
        outcome = self._session.checkpoint(
            checkpoint,
            effect_ref=effect_ref,
            completion=completion,
        )
        return None if outcome.accepted else outcome.rejected_effect()

    def _writeback_effect(
        self,
        result: Mapping[str, Any],
        *,
        completion_intent_error: str | None,
        terminal_closeout_required: bool,
        writeback: TurnResultEffect,
        completion_writeback: TurnResultEffect | None,
    ) -> TurnEffect:
        def writeback_effect(effect_ref: str) -> Mapping[str, Any]:
            if completion_intent_error:
                return {
                    "ok": False,
                    "appended": False,
                    "reason": completion_intent_error,
                }
            rejected = self._rejected_effect(
                "durable_writeback",
                effect_ref=effect_ref,
            )
            if rejected is not None:
                return rejected
            if (
                result.get("result_kind")
                == LoopXTurnResultKind.VALIDATED_COMPLETION.value
                and not terminal_closeout_required
            ):
                if completion_writeback is None:
                    raise ValueError(
                        "validated_completion requires a todo lifecycle adapter"
                    )
                callback_payload = invoke_result_effect(
                    completion_writeback,
                    result,
                    effect_ref,
                )
                completion = completion_writeback_outcome(
                    callback_payload,
                    plan=self._plan,
                )
                if completion is None:
                    return {
                        "ok": False,
                        "appended": False,
                        "reason": str(
                            callback_payload.get("reason")
                            or callback_payload.get("error")
                            or (
                                "todo lifecycle adapter returned an invalid "
                                "completion outcome"
                            )
                        ),
                    }
                return {**callback_payload, "completion": completion}
            return invoke_result_effect(writeback, result, effect_ref)

        return writeback_effect

    def _guarded_effect(
        self,
        checkpoint: str,
        effect: TurnEffect,
    ) -> TurnEffect:
        if self._session is None:
            return effect

        def guarded(effect_ref: str) -> Mapping[str, Any]:
            rejected = self._rejected_effect(checkpoint, effect_ref=effect_ref)
            return rejected if rejected is not None else effect(effect_ref)

        return guarded

    def _active_completion(self) -> dict[str, Any] | None:
        stored = self._journal.get("terminal_closeout")
        if not isinstance(stored, Mapping):
            stored = self._journal.get("writeback")
        return (
            completion_writeback_outcome(stored, plan=self._plan)
            if isinstance(stored, Mapping)
            else None
        )

    def _spend_effect(
        self,
        spend: TurnEffect,
        *,
        result: Mapping[str, Any],
        terminal_closeout_required: bool,
    ) -> TurnEffect:
        if self._session is None:
            return spend

        def guarded_spend(effect_ref: str) -> Mapping[str, Any]:
            rejected = self._rejected_effect("quota_spend", effect_ref=effect_ref)
            if rejected is not None:
                return rejected
            if (
                result.get("result_kind")
                == LoopXTurnResultKind.VALIDATED_COMPLETION.value
                and not terminal_closeout_required
            ):
                completion = self._active_completion()
                if completion is None:
                    return {
                        "ok": False,
                        "appended": False,
                        "reason": (
                            "validated completion has no durable authority "
                            "completion context"
                        ),
                    }
                rejected = self._rejected_effect(
                    "authority_complete",
                    effect_ref=effect_ref,
                    completion=completion,
                )
                if rejected is not None:
                    return rejected
            return invoke_turn_effect(spend, effect_ref)

        return guarded_spend

    def settlement_effects(
        self,
        *,
        result: Mapping[str, Any],
        writeback: TurnResultEffect,
        completion_writeback: TurnResultEffect | None,
        completion_intent: TurnResultEffect | None,
        terminal_closeout: TurnResultEffect | None,
        spend: TurnEffect,
        terminal_checkpoint: TurnTerminalCheckpoint,
    ) -> TurnAuthoritySettlementEffects:
        """Compose each checkpoint with the effect it fences."""

        terminal_closeout_required = False
        completion_intent_error = None
        if result.get("result_kind") == LoopXTurnResultKind.VALIDATED_COMPLETION.value:
            if (
                completion_writeback is None
                or completion_intent is None
                or terminal_closeout is None
            ):
                raise ValueError(
                    "validated_completion requires intent, lifecycle writeback, "
                    "and terminal closeout adapters"
                )
            terminal_closeout_required, completion_intent_error = (
                terminal_closeout_requirement(
                    plan=self._plan,
                    result=result,
                    journal=self._journal,
                    completion_intent=completion_intent,
                )
            )
        terminal_effect = None
        effective_terminal_checkpoint = None
        if terminal_closeout_required:
            if terminal_closeout is None:
                raise ValueError("terminal closeout adapter is required")
            terminal_effect = self._guarded_effect(
                "terminal_closeout",
                verified_terminal_closeout_effect(
                    terminal_closeout,
                    result=result,
                    plan=self._plan,
                ),
            )
            effective_terminal_checkpoint = terminal_checkpoint
        return TurnAuthoritySettlementEffects(
            writeback=self._writeback_effect(
                result,
                completion_intent_error=completion_intent_error,
                terminal_closeout_required=terminal_closeout_required,
                writeback=writeback,
                completion_writeback=completion_writeback,
            ),
            spend=self._spend_effect(
                spend,
                result=result,
                terminal_closeout_required=terminal_closeout_required,
            ),
            terminal_closeout=terminal_effect,
            terminal_checkpoint=effective_terminal_checkpoint,
            terminal_closeout_required=terminal_closeout_required,
        )

    def run_scheduler(
        self,
        scheduler: TurnScheduler,
        spend_payload: dict[str, Any],
        *,
        terminal_closeout_required: bool,
    ) -> dict[str, Any]:
        """Complete terminal authority, then fence the scheduler effect."""

        if self._session is None:
            return scheduler(spend_payload)
        rejected = None
        if terminal_closeout_required:
            terminal_payload = self._journal.get("terminal_closeout")
            completion = (
                completion_writeback_outcome(terminal_payload, plan=self._plan)
                if isinstance(terminal_payload, Mapping)
                else None
            )
            if completion is None:
                raise RuntimeError(
                    "terminal completion has no durable authority completion context"
                )
            rejected = self._rejected_effect(
                "authority_complete",
                effect_ref=f"{self._session.effect_id}#terminal_closeout",
                completion=completion,
            )
        if rejected is None:
            rejected = self._rejected_effect(
                "scheduler",
                effect_ref=f"{self._session.effect_id}#scheduler",
            )
        if rejected is not None:
            return {
                "completed": False,
                "acknowledged": False,
                "disposition": "authority_checkpoint_rejected",
                "reason": rejected.get("reason"),
            }
        return scheduler(spend_payload)


def build_turn_authority_checkpoint_controller(
    guard: TurnAuthorityCheckpointGuard | None,
    *,
    plan: Mapping[str, Any],
    transaction_plan: Mapping[str, Any],
    journal: dict[str, Any],
    turn_key: str,
    persist: PersistCheckpoint,
) -> TurnAuthorityCheckpointController:
    """Build the default-off authority composition for one durable Turn."""

    effective_guard = guard
    if effective_guard is None and "authority_checkpoint_guard" in journal:

        def reject_missing_guard(
            _request: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            return {
                "ok": False,
                "reason_code": "authority_guard_missing",
                "reason": (
                    "Turn was admitted under authority checkpoints but this "
                    "attempt has no authority guard"
                ),
            }

        effective_guard = reject_missing_guard

    session = None
    if effective_guard is not None:
        envelope_value = plan.get("turn_envelope")
        envelope = envelope_value if isinstance(envelope_value, Mapping) else {}
        selected_todo = selected_turn_todo(envelope)
        settlement_value = transaction_plan.get("settlement_plan")
        settlement_plan = (
            settlement_value if isinstance(settlement_value, Mapping) else {}
        )
        identity_value = settlement_plan.get("identity")
        identity = identity_value if isinstance(identity_value, Mapping) else {}
        session = TurnAuthorityCheckpointSession(
            effective_guard,
            goal_id=str(envelope.get("goal_id") or ""),
            agent_id=str(envelope.get("agent_id") or ""),
            todo_id=str(selected_todo.get("todo_id") or ""),
            turn_key=turn_key,
            effect_id=str(identity.get("effect_id") or ""),
            journal=journal,
            persist=persist,
        )
    return TurnAuthorityCheckpointController(
        session,
        plan=plan,
        journal=journal,
        persist=persist,
    )


def authority_journal_projection(journal: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only the public authority journal block in execution output."""

    value = journal.get("authority_checkpoint_guard")
    return (
        {"authority_checkpoint_guard": dict(value)}
        if isinstance(value, Mapping)
        else {}
    )
