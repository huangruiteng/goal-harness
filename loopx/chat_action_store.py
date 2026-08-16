"""Owner-local persistence for typed LoopX Chat action proposals."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
import uuid

from .file_lock import exclusive_file_lock
from .registry import atomic_write_json


CHAT_ACTION_STORE_SCHEMA_VERSION = "loopx_chat_action_store_v1"
CHAT_ACTION_PROPOSAL_SCHEMA_VERSION = "loopx_chat_action_proposal_v1"

ACTION_KINDS = {
    "goal.create",
    "goal.update",
    "todo.create",
    "todo.update",
    "agent.bind",
    "heartbeat.bind",
    "monitor.create",
    "monitor.update",
    "gate.resolve",
    "run.correct",
}
PROPOSAL_STATES = {
    "preview_ready",
    "applying",
    "gated",
    "failed",
    "rejected",
    "deferred",
    "cancelled",
    "stale",
    "applied",
}
RETRYABLE_PROPOSAL_STATES = {"preview_ready", "gated", "failed", "deferred"}

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_LOCAL_PATH = re.compile(
    r"(?:^|[\s\"'])(?:/Users/|/home/|/private/|/var/folders/|/tmp/|~[/\\]|file://)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?:bearer\s+[A-Za-z0-9._~+/-]+|sk-[A-Za-z0-9_-]{4,}|raw\s+(?:provider|tool)\s+(?:payload|output))",
    re.IGNORECASE,
)
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "credentials",
    "credential",
    "private_key",
    "raw_provider_payload",
    "provider_payload",
    "raw_tool_output",
    "tool_output",
    "stderr",
    "command",
}


class ActionConflictError(RuntimeError):
    """Raised when a typed action transition conflicts with durable state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _opaque_id(value: Any, *, field: str) -> str:
    token = str(value or "").strip()
    if not _OPAQUE_ID.fullmatch(token):
        raise ValueError(f"{field} must be a compact opaque id")
    return token


def _bounded_text(value: Any, *, field: str, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit or any(ord(character) < 32 for character in text):
        raise ValueError(f"{field} must be bounded visible text")
    return text


def _safe_json_value(value: Any, *, path: str = "payload") -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _LOCAL_PATH.search(value) or _SENSITIVE_TEXT.search(value):
            raise ValueError(f"{path} contains sensitive material")
        if len(value) > 8000 or any(ord(character) < 9 for character in value):
            raise ValueError(f"{path} must contain bounded public-safe text")
        return value
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key).strip()
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if not key or normalized_key in _SENSITIVE_KEYS:
                raise ValueError(f"{path}.{key or '<empty>'} is a sensitive field")
            safe[key] = _safe_json_value(item, path=f"{path}.{key}")
        return safe
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [
            _safe_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ValueError(f"{path} must be JSON-compatible")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ChatActionStore:
    """Persist typed action previews and receipts in an explicit local root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "actions.json"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if not self.path.exists():
            atomic_write_json(self.path, self._empty_payload())
        os.chmod(self.path, 0o600)

    @staticmethod
    def _empty_payload() -> dict[str, Any]:
        return {
            "schema_version": CHAT_ACTION_STORE_SCHEMA_VERSION,
            "proposals": {},
            "idempotency": {},
        }

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("typed Chat action store is unreadable") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != CHAT_ACTION_STORE_SCHEMA_VERSION:
            raise ValueError("typed Chat action store has an unsupported schema")
        if not isinstance(payload.get("proposals"), dict) or not isinstance(
            payload.get("idempotency"), dict
        ):
            raise ValueError("typed Chat action store is malformed")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.path, payload, preserve_mode=True)
        os.chmod(self.path, 0o600)

    def create_preview(
        self,
        *,
        action_kind: str,
        summary: str,
        normalized_parameters: Mapping[str, Any],
        context: Mapping[str, Any],
        expected_state_fingerprint: str,
        permission_classification: str,
        validation_evidence: Sequence[Any],
        available_transitions: Sequence[Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        selected_kind = str(action_kind or "").strip()
        if selected_kind not in ACTION_KINDS:
            raise ValueError(f"unsupported action_kind: {selected_kind or '<empty>'}")
        request = _safe_json_value(
            {
                "action_kind": selected_kind,
                "summary": _bounded_text(summary, field="summary"),
                "normalized_parameters": dict(normalized_parameters),
                "context": dict(context),
                "expected_state_fingerprint": _bounded_text(
                    expected_state_fingerprint,
                    field="expected_state_fingerprint",
                    limit=512,
                ),
                "permission_classification": _opaque_id(
                    permission_classification,
                    field="permission_classification",
                ),
                "validation_evidence": list(validation_evidence),
                "available_transitions": list(available_transitions),
            },
            path="preview",
        )
        key = _opaque_id(idempotency_key, field="idempotency_key")
        request_digest = _canonical_digest(request)
        with exclusive_file_lock(
            self.path,
            agent_id="loopx-chat",
            operation="create_chat_action_preview",
        ):
            payload = self._read()
            existing_binding = payload["idempotency"].get(key)
            if isinstance(existing_binding, dict):
                proposal_id = str(existing_binding.get("proposal_id") or "")
                if existing_binding.get("request_digest") != request_digest:
                    raise ActionConflictError("idempotency key already belongs to another preview")
                existing = payload["proposals"].get(proposal_id)
                if not isinstance(existing, dict):
                    raise ValueError("typed Chat action idempotency index is inconsistent")
                return existing

            now = _utc_now()
            proposal_id = f"proposal-{uuid.uuid4().hex}"
            proposal = {
                "schema_version": CHAT_ACTION_PROPOSAL_SCHEMA_VERSION,
                "proposal_id": proposal_id,
                **request,
                "idempotency_key": key,
                "request_digest": request_digest,
                "status": "preview_ready",
                "receipt": None,
                "gate": None,
                "failure": None,
                "checkpoint": None,
                "stale": None,
                "regenerated_from": None,
                "created_at": now,
                "updated_at": now,
                "cancelled_at": None,
                "rejected_at": None,
                "deferred_at": None,
                "applied_at": None,
            }
            payload["proposals"][proposal_id] = proposal
            payload["idempotency"][key] = {
                "proposal_id": proposal_id,
                "request_digest": request_digest,
            }
            self._write(payload)
            return proposal

    def load(self, proposal_id: str) -> dict[str, Any] | None:
        token = _opaque_id(proposal_id, field="proposal_id")
        proposal = self._read()["proposals"].get(token)
        if proposal is None:
            return None
        if not isinstance(proposal, dict) or proposal.get("status") not in PROPOSAL_STATES:
            raise ValueError("typed Chat action proposal is malformed")
        return proposal

    def list(
        self,
        *,
        goal_id: str | None = None,
        context_kind: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        selected_goal = _opaque_id(goal_id, field="goal_id") if goal_id else None
        selected_context = (
            _opaque_id(context_kind, field="context_kind") if context_kind else None
        )
        if status and status not in PROPOSAL_STATES:
            raise ValueError("status must be a supported typed action state")
        proposals: list[dict[str, Any]] = []
        for raw in self._read()["proposals"].values():
            if not isinstance(raw, dict) or raw.get("status") not in PROPOSAL_STATES:
                continue
            context = raw.get("context")
            context = context if isinstance(context, dict) else {}
            parameters = raw.get("normalized_parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            proposal_goal = str(context.get("goal_id") or parameters.get("goal_id") or "")
            if selected_goal and proposal_goal != selected_goal:
                continue
            if selected_context and str(context.get("kind") or "") != selected_context:
                continue
            if status and raw.get("status") != status:
                continue
            proposals.append(raw)
        return sorted(
            proposals,
            key=lambda proposal: (
                str(proposal.get("updated_at") or ""),
                str(proposal.get("proposal_id") or ""),
            ),
            reverse=True,
        )

    def cancel(self, proposal_id: str) -> dict[str, Any]:
        token = _opaque_id(proposal_id, field="proposal_id")
        with exclusive_file_lock(
            self.path,
            agent_id="loopx-chat",
            operation="cancel_chat_action_preview",
        ):
            payload = self._read()
            proposal = payload["proposals"].get(token)
            if not isinstance(proposal, dict):
                raise KeyError("typed Chat action proposal was not found")
            if proposal.get("status") == "cancelled":
                return proposal
            if proposal.get("status") not in {"preview_ready", "gated", "failed", "deferred"}:
                raise ActionConflictError(
                    f"proposal in {proposal.get('status')} state cannot be cancelled"
                )
            now = _utc_now()
            proposal["status"] = "cancelled"
            proposal["cancelled_at"] = now
            proposal["updated_at"] = now
            self._write(payload)
            return proposal

    def start_apply(self, proposal_id: str) -> dict[str, Any]:
        """Persist the execution boundary before any canonical write is attempted."""

        return self._transition(
            proposal_id,
            from_states=RETRYABLE_PROPOSAL_STATES,
            to_state="applying",
            updates={"gate": None, "failure": None},
            idempotent_states={"applying", "applied"},
        )

    def mark_gated(self, proposal_id: str, *, gate: Mapping[str, Any]) -> dict[str, Any]:
        safe_gate = _safe_json_value(dict(gate), path="gate")
        if not isinstance(safe_gate, dict):
            raise ValueError("gate must be an object")
        _opaque_id(safe_gate.get("kind"), field="gate.kind")
        return self._transition(
            proposal_id,
            from_states={"applying", "preview_ready"},
            to_state="gated",
            updates={"gate": safe_gate, "failure": None},
            idempotent_states={"gated"},
        )

    def mark_failed(
        self,
        proposal_id: str,
        *,
        error_code: str,
        message: str,
    ) -> dict[str, Any]:
        failure = _safe_json_value(
            {
                "error_code": _opaque_id(error_code, field="error_code"),
                "message": _bounded_text(message, field="message", limit=1000),
                "failed_at": _utc_now(),
                "retry_safe": True,
            },
            path="failure",
        )
        return self._transition(
            proposal_id,
            from_states={"applying", "preview_ready", "gated"},
            to_state="failed",
            updates={"failure": failure},
            idempotent_states={"failed"},
        )

    def save_checkpoint(
        self,
        proposal_id: str,
        *,
        step: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        safe_step = _opaque_id(step, field="step")
        safe_receipt = _safe_json_value(dict(receipt), path="checkpoint.receipt")
        if not isinstance(safe_receipt, dict):
            raise ValueError("checkpoint receipt must be an object")
        token = _opaque_id(proposal_id, field="proposal_id")
        with exclusive_file_lock(
            self.path,
            agent_id="loopx-chat",
            operation="checkpoint_chat_action_preview",
        ):
            payload = self._read()
            proposal = payload["proposals"].get(token)
            if not isinstance(proposal, dict):
                raise KeyError("typed Chat action proposal was not found")
            if proposal.get("status") not in {"applying", "gated", "failed"}:
                raise ActionConflictError(
                    f"proposal in {proposal.get('status')} state cannot save a checkpoint"
                )
            checkpoint = proposal.get("checkpoint")
            checkpoint = dict(checkpoint) if isinstance(checkpoint, dict) else {"steps": {}}
            steps = checkpoint.get("steps")
            steps = dict(steps) if isinstance(steps, dict) else {}
            steps[safe_step] = safe_receipt
            checkpoint["steps"] = steps
            checkpoint["last_completed_step"] = safe_step
            checkpoint["updated_at"] = _utc_now()
            proposal["checkpoint"] = checkpoint
            proposal["updated_at"] = checkpoint["updated_at"]
            self._write(payload)
            return proposal

    def mark_rejected(self, proposal_id: str) -> dict[str, Any]:
        now = _utc_now()
        return self._transition(
            proposal_id,
            from_states={"preview_ready", "gated", "deferred"},
            to_state="rejected",
            updates={"rejected_at": now},
            idempotent_states={"rejected"},
        )

    def mark_deferred(self, proposal_id: str) -> dict[str, Any]:
        now = _utc_now()
        return self._transition(
            proposal_id,
            from_states={"preview_ready", "gated", "failed"},
            to_state="deferred",
            updates={"deferred_at": now},
            idempotent_states={"deferred"},
        )

    def link_regeneration(self, proposal_id: str, *, regenerated_from: str) -> dict[str, Any]:
        token = _opaque_id(proposal_id, field="proposal_id")
        source = _opaque_id(regenerated_from, field="regenerated_from")
        with exclusive_file_lock(
            self.path,
            agent_id="loopx-chat",
            operation="link_chat_action_regeneration",
        ):
            payload = self._read()
            proposal = payload["proposals"].get(token)
            if not isinstance(proposal, dict):
                raise KeyError("typed Chat action proposal was not found")
            proposal["regenerated_from"] = source
            proposal["updated_at"] = _utc_now()
            self._write(payload)
            return proposal

    def _transition(
        self,
        proposal_id: str,
        *,
        from_states: set[str],
        to_state: str,
        updates: Mapping[str, Any],
        idempotent_states: set[str],
    ) -> dict[str, Any]:
        token = _opaque_id(proposal_id, field="proposal_id")
        if to_state not in PROPOSAL_STATES:
            raise ValueError("unsupported typed action state")
        with exclusive_file_lock(
            self.path,
            agent_id="loopx-chat",
            operation=f"transition_chat_action_{to_state}",
        ):
            payload = self._read()
            proposal = payload["proposals"].get(token)
            if not isinstance(proposal, dict):
                raise KeyError("typed Chat action proposal was not found")
            status = str(proposal.get("status") or "")
            if status in idempotent_states:
                return proposal
            if status not in from_states:
                raise ActionConflictError(f"proposal in {status} state cannot become {to_state}")
            proposal["status"] = to_state
            proposal.update(_safe_json_value(dict(updates), path="transition"))
            proposal["updated_at"] = _utc_now()
            self._write(payload)
            return proposal

    def apply(
        self,
        proposal_id: str,
        *,
        current_state_fingerprint: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        token = _opaque_id(proposal_id, field="proposal_id")
        current_fingerprint = _bounded_text(
            current_state_fingerprint,
            field="current_state_fingerprint",
            limit=512,
        )
        with exclusive_file_lock(
            self.path,
            agent_id="loopx-chat",
            operation="apply_chat_action_preview",
        ):
            payload = self._read()
            proposal = payload["proposals"].get(token)
            if not isinstance(proposal, dict):
                raise KeyError("typed Chat action proposal was not found")
            status = str(proposal.get("status") or "")
            if status == "applied":
                return proposal
            if status not in {"preview_ready", "applying"}:
                raise ActionConflictError(f"proposal in {status} state cannot be applied")
            expected_fingerprint = str(proposal.get("expected_state_fingerprint") or "")
            now = _utc_now()
            if current_fingerprint != expected_fingerprint:
                proposal["status"] = "stale"
                proposal["stale"] = {
                    "expected_state_fingerprint": expected_fingerprint,
                    "current_state_fingerprint": current_fingerprint,
                    "detected_at": now,
                }
                proposal["updated_at"] = now
                self._write(payload)
                return proposal

            safe_receipt = _safe_json_value(dict(receipt), path="receipt")
            if not isinstance(safe_receipt, dict):
                raise ValueError("receipt must be an object")
            _opaque_id(safe_receipt.get("receipt_id"), field="receipt.receipt_id")
            _opaque_id(safe_receipt.get("outcome"), field="receipt.outcome")
            if safe_receipt.get("projection_verified") is not True:
                raise ValueError("receipt.projection_verified must be true")
            proposal["status"] = "applied"
            proposal["receipt"] = safe_receipt
            proposal["applied_at"] = now
            proposal["updated_at"] = now
            self._write(payload)
            return proposal
