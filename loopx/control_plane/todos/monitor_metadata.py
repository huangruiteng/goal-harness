from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..runtime.time import parse_timestamp
from ..scheduler.monitor_todo import (
    monitor_cadence_delta,
    monitor_next_due_at,
    parse_monitor_counter,
)
from .contract import (
    TODO_MONITOR_METADATA_FIELDS,
    TODO_TASK_CLASS_MONITOR,
    normalize_todo_watch_only,
)


@dataclass(frozen=True)
class MonitorPollObservation:
    """One monitor result whose state transition must be planned under lock."""

    generated_at: str
    result_hash: str
    material_change: bool
    monitor_effect_id: str | None = None
    target_key: str | None = None
    cadence: str | None = None
    next_due_at: str | None = None


MonitorMetadataInput = dict[str, Any] | MonitorPollObservation | None


def plan_monitor_poll_metadata(
    *,
    existing: Mapping[str, Any],
    observation: MonitorPollObservation,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive one monotonic monitor transition from the locked Todo state."""

    if str(existing.get("task_class") or "") != TODO_TASK_CLASS_MONITOR:
        raise ValueError(
            "monitor poll observation requires task_class=continuous_monitor"
        )
    result_hash = str(observation.result_hash or "").strip()
    if not result_hash:
        raise ValueError("monitor todo writeback requires --result-hash")

    existing_target_key = str(existing.get("target_key") or "").strip()
    requested_target_key = str(observation.target_key or "").strip()
    if (
        requested_target_key
        and existing_target_key
        and requested_target_key != existing_target_key
    ):
        raise ValueError(
            f"monitor poll target_key resolves to {existing_target_key!r}, "
            f"not {requested_target_key!r}"
        )
    target_key = requested_target_key or existing_target_key
    cadence = str(observation.cadence or existing.get("cadence") or "").strip()
    next_due_at = monitor_next_due_at(
        generated_at=observation.generated_at,
        cadence=cadence,
        explicit_next_due_at=observation.next_due_at,
    )
    if not observation.material_change and not next_due_at:
        raise ValueError(
            "unchanged monitor todo writeback requires --next-due-at or a "
            "parseable cadence such as 30m/2h/1d"
        )

    monitor_effect_id = str(observation.monitor_effect_id or "").strip()
    existing_effect_id = str(existing.get("monitor_effect_id") or "").strip()
    if monitor_effect_id and monitor_effect_id == existing_effect_id:
        replay_facts = {
            "result_hash": result_hash,
            "material_change": "true" if observation.material_change else "false",
            "last_checked_at": observation.generated_at,
            "target_key": target_key,
            "cadence": cadence,
            "next_due_at": next_due_at or "",
        }
        conflicts = [
            key
            for key, expected in replay_facts.items()
            if str(existing.get(key) or "").strip() != str(expected or "").strip()
        ]
        if conflicts:
            raise ValueError(
                "monitor effect identity is already bound to different "
                f"observation fields: {', '.join(conflicts)}"
            )
        existing_metadata = {
            key: existing[key]
            for key in TODO_MONITOR_METADATA_FIELDS
            if existing.get(key) is not None
        }
        return existing_metadata, {
            "monitor_effect_id": monitor_effect_id,
            "provider_replayed": True,
            "result_hash": result_hash,
            "material_change": observation.material_change,
            "material_change_applied": False,
            "material_change_generation": parse_monitor_counter(
                existing.get("material_change_generation")
            ),
            "consecutive_no_change": parse_monitor_counter(
                existing.get("consecutive_no_change")
            ),
            "last_checked_at": observation.generated_at,
            "target_key": target_key or None,
            "cadence": cadence or None,
            "next_due_at": next_due_at,
        }

    if monitor_effect_id and existing_effect_id:
        persisted_at = parse_timestamp(existing.get("last_checked_at"))
        observed_at = parse_timestamp(observation.generated_at)
        if persisted_at is not None and observed_at is not None and observed_at <= persisted_at:
            raise ValueError(
                "monitor observation is older than the persisted monitor effect"
            )

    previous_hash = str(existing.get("result_hash") or "").strip()
    previous_no_change = parse_monitor_counter(existing.get("consecutive_no_change"))
    previous_generation = parse_monitor_counter(
        existing.get("material_change_generation")
    )
    advances_generation = bool(
        observation.material_change and result_hash != previous_hash
    )
    generation = previous_generation + (1 if advances_generation else 0)
    consecutive_no_change = (
        0
        if observation.material_change
        or (previous_hash and previous_hash != result_hash)
        else previous_no_change + 1
    )

    metadata: dict[str, Any] = {
        "last_checked_at": observation.generated_at,
        "result_hash": result_hash,
        "consecutive_no_change": str(consecutive_no_change),
        "material_change": "true" if observation.material_change else "false",
        "material_change_generation": str(generation),
    }
    if monitor_effect_id:
        metadata["monitor_effect_id"] = monitor_effect_id
    if target_key:
        metadata["target_key"] = target_key
    if cadence:
        metadata["cadence"] = cadence
    if next_due_at:
        metadata["next_due_at"] = next_due_at
    return metadata, {
        "monitor_effect_id": monitor_effect_id or None,
        "provider_replayed": False,
        "result_hash": result_hash,
        "material_change": observation.material_change,
        "material_change_applied": advances_generation,
        "material_change_generation": generation,
        "consecutive_no_change": consecutive_no_change,
        "last_checked_at": observation.generated_at,
        "target_key": target_key or None,
        "cadence": cadence or None,
        "next_due_at": next_due_at,
    }


def resolve_monitor_metadata_input(
    *,
    existing: Mapping[str, Any],
    monitor_metadata: MonitorMetadataInput,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(monitor_metadata, MonitorPollObservation):
        return monitor_metadata, None
    return plan_monitor_poll_metadata(
        existing=existing,
        observation=monitor_metadata,
    )


def normalize_monitor_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in TODO_MONITOR_METADATA_FIELDS:
            continue
        if value is None:
            normalized[key] = None
            continue
        candidate = str(value or "").strip()
        if candidate:
            normalized[key] = candidate
    if (
        normalized.get("cadence") is not None
        and monitor_cadence_delta(normalized["cadence"]) is None
    ):
        raise ValueError("--cadence must look like 30m, 2h, or 1d")
    if normalized.get("next_due_at") is not None and parse_timestamp(normalized["next_due_at"]) is None:
        raise ValueError("--next-due-at must be an ISO timestamp")
    if normalized.get("expires_at") is not None and parse_timestamp(normalized["expires_at"]) is None:
        raise ValueError("--expires-at must be an ISO timestamp")
    if normalized.get("last_checked_at") is not None and parse_timestamp(normalized["last_checked_at"]) is None:
        raise ValueError("--last-checked-at must be an ISO timestamp")
    if normalized.get("consecutive_no_change") is not None:
        try:
            int(normalized["consecutive_no_change"])
        except ValueError as exc:
            raise ValueError("--consecutive-no-change must be an integer") from exc
    if normalized.get("material_change_generation") is not None:
        try:
            generation = int(normalized["material_change_generation"])
        except ValueError as exc:
            raise ValueError(
                "--material-change-generation must be an integer"
            ) from exc
        if generation < 0:
            raise ValueError(
                "--material-change-generation must be a non-negative integer"
            )
    if normalized.get("material_change") is not None and normalized["material_change"] not in {"true", "false"}:
        raise ValueError("--material-change metadata must be true or false")
    if normalized.get("watch_only") is not None and normalize_todo_watch_only(
        normalized["watch_only"]
    ) is None:
        raise ValueError("--watch-only metadata must be true or false")
    return normalized


def materialize_monitor_schedule(
    *,
    task_class: str | None,
    monitor_metadata: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Materialize the first due time for a cadence-only monitor mutation."""

    if task_class != TODO_TASK_CLASS_MONITOR:
        return monitor_metadata
    if monitor_metadata.get("next_due_at") is not None:
        return monitor_metadata
    cadence = monitor_metadata.get("cadence")
    if cadence is None:
        return monitor_metadata
    next_due_at = monitor_next_due_at(
        generated_at=generated_at,
        cadence=cadence,
    )
    if next_due_at is None:
        return monitor_metadata
    return {**monitor_metadata, "next_due_at": next_due_at}


def require_continuous_monitor_boundedness(
    *,
    task_class: str | None,
    resume_when: str | None,
    monitor_metadata: dict[str, Any] | None,
) -> None:
    if task_class != TODO_TASK_CLASS_MONITOR:
        return
    metadata = monitor_metadata or {}
    if (
        str(metadata.get("expires_at") or "").strip()
        or str(resume_when or "").strip()
        or normalize_todo_watch_only(metadata.get("watch_only")) is True
    ):
        return
    raise ValueError(
        "continuous_monitor requires one of: --expires-at, --resume-when, "
        "or --watch-only"
    )


def validate_monitor_metadata_update(
    *,
    monitor_metadata: dict[str, Any] | None,
    existing: Mapping[str, Any],
    role: str,
    task_class: str | None,
    generated_at: str,
    resume_when: str | None,
    enforce_boundedness: bool,
) -> dict[str, Any]:
    normalized = require_monitor_metadata_scope(
        monitor_metadata=monitor_metadata,
        role=role,
        task_class=task_class,
        generated_at=generated_at,
    )
    if enforce_boundedness:
        effective = {
            key: value
            for key, value in {
                **{
                    key: existing.get(key)
                    for key in ("expires_at", "watch_only")
                    if existing.get(key) is not None
                },
                **normalized,
            }.items()
            if value is not None
        }
        require_continuous_monitor_boundedness(
            task_class=task_class,
            resume_when=resume_when,
            monitor_metadata=effective,
        )
    return normalized


def require_monitor_metadata_scope(
    *,
    monitor_metadata: dict[str, Any] | None,
    role: str,
    task_class: str | None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_monitor_metadata(monitor_metadata)
    if not normalized:
        return {}
    schedule_fields = {k for k, v in normalized.items() if v is not None and k != "target_key"}
    if schedule_fields and (role != "agent" or task_class != "continuous_monitor"):
        raise ValueError(
            "monitor schedule metadata requires --role agent --task-class continuous_monitor"
        )
    if normalized.get("target_key") is not None and role != "agent":
        raise ValueError("target_key requires --role agent")
    if generated_at is None:
        return normalized
    return materialize_monitor_schedule(
        task_class=task_class,
        monitor_metadata=normalized,
        generated_at=generated_at,
    )
