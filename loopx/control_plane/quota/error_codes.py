from __future__ import annotations

import json
from enum import StrEnum


class QuotaCommandValidationError(ValueError):
    """Public-safe diagnostic for an invalid ``loopx quota`` invocation."""


class HeartbeatReceiptIdentityConflictError(ValueError):
    """Public-safe diagnostic for a same-turn settlement identity conflict."""


class QuotaIdentityPrecondition(StrEnum):
    """Typed identity admission preconditions for scoped quota decisions."""

    PUBLIC_SAFE_AGENT_ID = "public_safe_agent_id"
    REGISTERED_AGENT_ROSTER_PRESENT = "registered_agent_roster_present"
    REQUESTED_AGENT_REGISTERED = "requested_agent_registered"


class QuotaIdentityPreconditionError(ValueError):
    """Public-safe failure raised before a scoped quota decision can be built."""

    def __init__(
        self,
        precondition: QuotaIdentityPrecondition,
        *,
        agent_id: str | None = None,
    ) -> None:
        self.precondition = precondition
        self.agent_id = agent_id
        if precondition is QuotaIdentityPrecondition.PUBLIC_SAFE_AGENT_ID:
            self.error_code = "quota_agent_id_invalid"
            self.recommended_action = (
                "use a public-safe agent id registered in the selected registry, "
                "then retry"
            )
            reason = "agent_id must be a public-safe registered agent id"
        elif precondition is QuotaIdentityPrecondition.REGISTERED_AGENT_ROSTER_PRESENT:
            self.error_code = "quota_agent_registry_roster_missing"
            self.recommended_action = (
                "register this agent in coordination.registered_agents of the "
                "selected registry, then rerun quota should-run with the same "
                "--registry and --agent-id"
            )
            reason = "selected registry goal is missing coordination.registered_agents"
        else:
            self.error_code = "quota_agent_not_registered"
            self.recommended_action = (
                "register this agent in coordination.registered_agents of the "
                "selected registry, then rerun quota should-run with the same "
                "--registry and --agent-id"
            )
            reason = (
                f"agent_id={agent_id!r} is not registered in the selected registry goal"
            )
        super().__init__(reason)


def quota_error_code(exc: BaseException) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "quota_state_invalid_json"
    if isinstance(exc, QuotaCommandValidationError):
        return "quota_invalid_arguments"
    if isinstance(exc, QuotaIdentityPreconditionError):
        return exc.error_code
    if isinstance(exc, HeartbeatReceiptIdentityConflictError):
        return "heartbeat_receipt_identity_conflict"
    if isinstance(exc, PermissionError):
        return "quota_state_permission_denied"
    if isinstance(exc, OSError):
        return "quota_state_io_failed"
    if isinstance(exc, KeyError):
        return "quota_state_missing_field"
    if isinstance(exc, TypeError):
        return "quota_state_shape_error"
    return "quota_unexpected_collection_error"
