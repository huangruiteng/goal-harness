from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .effect_runtime import EffectRuntimeRejected, effect_runtime_result


CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION = (
    "loopx_capability_hook_registration_v0"
)
INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION = (
    "loopx_interaction_projection_hook_result_v0"
)
INTERACTION_PROJECTION_HOOK_DISPATCH_SCHEMA_VERSION = (
    "loopx_interaction_projection_hook_dispatch_v0"
)
TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION = (
    "loopx_turn_start_capability_hook_registration_v0"
)
TURN_START_HOOK_RESULT_SCHEMA_VERSION = "loopx_turn_start_capability_hook_result_v0"
TURN_START_HOOK_DISPATCH_SCHEMA_VERSION = "loopx_turn_start_capability_hook_dispatch_v0"

InteractionProjectionProducer = Callable[[], Mapping[str, Any]]
TurnStartProducer = Callable[[], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class InteractionProjectionHookRegistration:
    """One read-only capability contribution to an interaction contract."""

    hook_id: str
    capability_id: str
    projection_slots: tuple[str, ...]
    requested_read_scope: tuple[str, ...]
    producer: InteractionProjectionProducer
    max_result_bytes: int = 16 * 1024

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION,
            "hook_id": self.hook_id,
            "capability_id": self.capability_id,
            "phase": "interaction_projection",
            "projection_slots": list(self.projection_slots),
            "budget": {
                "max_invocations_per_dispatch": 1,
                "max_result_bytes": self.max_result_bytes,
            },
            "failure_policy": "isolate",
            "requested_read_scope": list(self.requested_read_scope),
            "requested_write_scope": [],
        }


@dataclass(frozen=True, slots=True)
class TurnStartHookRegistration:
    """One bounded provider observation before a LoopX turn is selected."""

    hook_id: str
    capability_id: str
    requested_read_scope: tuple[str, ...]
    requested_write_scope: tuple[str, ...]
    producer: TurnStartProducer
    max_result_bytes: int = 16 * 1024

    def contract(self) -> dict[str, Any]:
        return {
            "schema_version": TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION,
            "hook_id": self.hook_id,
            "capability_id": self.capability_id,
            "phase": "turn_start",
            "budget": {
                "max_invocations_per_dispatch": 1,
                "max_result_bytes": self.max_result_bytes,
            },
            "failure_policy": "isolate",
            "requested_read_scope": list(self.requested_read_scope),
            "requested_write_scope": list(self.requested_write_scope),
        }


def dispatch_interaction_projection_hooks(
    registrations: Sequence[InteractionProjectionHookRegistration] | None,
) -> dict[str, Any]:
    """Validate and combine read-only projections without granting effects."""

    projections: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    projected_hooks: list[str] = []
    for registration in registrations or ():
        try:
            effect_runtime_result(
                "capability_hook.interaction_projection.validate_registration",
                {"registration": registration.contract()},
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="registration_rejected")
            )
            continue
        try:
            result = dict(registration.producer())
        except Exception:  # Capability failures are isolated by contract.
            failures.append(
                _hook_failure(registration, error_code="producer_failed")
            )
            continue
        try:
            normalized = effect_runtime_result(
                "capability_hook.interaction_projection.validate",
                {
                    "registration": registration.contract(),
                    "result": result,
                },
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="contract_rejected")
            )
            continue
        if not isinstance(normalized, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        if normalized.get("status") != "projected":
            continue
        slot = normalized.get("projection_slot")
        projection = normalized.get("projection")
        if not isinstance(slot, str) or not isinstance(projection, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        if slot in projections:
            failures.append(
                _hook_failure(registration, error_code="projection_slot_conflict")
            )
            continue
        projections[slot] = dict(projection)
        projected_hooks.append(registration.hook_id)
    return {
        "schema_version": INTERACTION_PROJECTION_HOOK_DISPATCH_SCHEMA_VERSION,
        "phase": "interaction_projection",
        "registered_count": len(registrations or ()),
        "projected_hooks": projected_hooks,
        "projections": projections,
        "failures": failures,
    }


def dispatch_turn_start_hooks(
    registrations: Sequence[TurnStartHookRegistration] | None,
) -> dict[str, Any]:
    """Run bounded pre-turn observations without exposing provider payloads."""

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_hook_ids: set[str] = set()
    ordered = sorted(registrations or (), key=lambda item: item.hook_id)
    for registration in ordered:
        if registration.hook_id in seen_hook_ids:
            failures.append(_hook_failure(registration, error_code="duplicate_hook_id"))
            continue
        seen_hook_ids.add(registration.hook_id)
        try:
            effect_runtime_result(
                "capability_hook.turn_start.validate_registration",
                {"registration": registration.contract()},
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(
                _hook_failure(registration, error_code="registration_rejected")
            )
            continue
        try:
            result = dict(registration.producer())
        except Exception:  # noqa: BLE001 - capability failures are isolated.
            failures.append(_hook_failure(registration, error_code="producer_failed"))
            continue
        try:
            normalized = effect_runtime_result(
                "capability_hook.turn_start.validate",
                {
                    "registration": registration.contract(),
                    "result": result,
                },
            )
        except (EffectRuntimeRejected, RuntimeError, TypeError, ValueError):
            failures.append(_hook_failure(registration, error_code="contract_rejected"))
            continue
        if not isinstance(normalized, Mapping):
            failures.append(
                _hook_failure(registration, error_code="runtime_result_invalid")
            )
            continue
        results.append(dict(normalized))
    return {
        "schema_version": TURN_START_HOOK_DISPATCH_SCHEMA_VERSION,
        "phase": "turn_start",
        "registered_count": len(registrations or ()),
        "invoked_count": len(results),
        "results": results,
        "failures": failures,
    }


def _hook_failure(
    registration: InteractionProjectionHookRegistration | TurnStartHookRegistration,
    *,
    error_code: str,
) -> dict[str, str]:
    return {
        "hook_id": registration.hook_id,
        "capability_id": registration.capability_id,
        "error_code": error_code,
    }
