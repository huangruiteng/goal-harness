"""Codex session rollout usage producer for the ``run_usage_v0`` ledger seam.

This is the first shipped measurement source behind
``ingest_usage_into_run_record``: it reads one locally stored Codex CLI
session rollout (JSONL) and returns the session-cumulative token usage as a
provider-neutral observation. Only aggregate ``token_count`` totals, the model
id, the session id, and event timestamps are read; prompts, completions, tool
output, and any other conversational content never enter the measurement.

The rollout must be bound explicitly by the caller. This module performs no
session discovery under ``CODEX_HOME``: guessing the session (for example by
cwd and mtime) risks attributing one concurrent session's spend to another
run, and a wrong attribution is worse than an unknown one. Automatic
discovery, if ever added, needs its own explicitly reviewed contract.

Cumulative-to-delta conversion happens at the run-write boundary: the caller
persists each accepted observation with :func:`store_usage_snapshot` and
passes it back through :func:`previous_snapshot_for_observation` so an
unchanged rollout replays as a zero delta and a grown rollout books only the
non-negative increment. Baselines are kept per session id: interleaved
sessions (A, then B, then A again) each rebase against their own last
accepted cumulative snapshot, so a returning session never re-books its full
total as new spend. Missing optional metrics stay unknown, never zero.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .usage_collector import UsageRowError

CODEX_USAGE_PROVIDER = "codex"
USAGE_SNAPSHOT_SCHEMA_VERSION = "goal_usage_snapshot_v1"
USAGE_SNAPSHOT_FILENAME = "usage_snapshot.json"
_SNAPSHOT_FIELDS = (
    "session_id",
    "source_snapshot_id",
    "input_tokens",
    "output_tokens",
    "cache_tokens",
    "cost_usd",
    "duration_ms",
    "provider",
    "model",
)


class CodexSessionUsageError(UsageRowError):
    """Fail-closed diagnostic for unreadable or unusable Codex rollouts."""


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def read_codex_session_usage(rollout_path: Path) -> dict[str, Any]:
    """Return one cumulative usage observation from a Codex session rollout.

    Counters are the session-cumulative totals from the newest ``token_count``
    event. ``source_snapshot_id`` binds the observation to the session id plus
    that event's timestamp, so replaying an unchanged rollout keeps the same
    identity (idempotent zero delta) while a grown rollout produces a new
    identity whose delta is taken against the stored previous observation.
    """
    path = Path(rollout_path).expanduser()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CodexSessionUsageError(
            f"cannot read codex session rollout: {exc}"
        ) from exc

    session_id = ""
    session_started_at: datetime | None = None
    model = ""
    last_totals: Mapping[str, Any] | None = None
    last_totals_at = ""
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            # The Codex CLI appends to the rollout while sessions run; a torn
            # trailing line is not an integrity failure for earlier events.
            continue
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if kind == "session_meta":
            session_id = str(
                payload.get("session_id") or payload.get("id") or ""
            ).strip()
            session_started_at = _parse_timestamp(
                payload.get("timestamp") or item.get("timestamp")
            )
        elif kind == "turn_context":
            model_text = str(payload.get("model") or "").strip()
            if model_text:
                model = model_text
        elif kind == "event_msg" and str(payload.get("type") or "") == "token_count":
            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            totals = info.get("total_token_usage")
            if isinstance(totals, Mapping):
                last_totals = totals
                last_totals_at = str(item.get("timestamp") or "").strip()

    if not session_id:
        raise CodexSessionUsageError(
            f"codex session rollout has no session_meta id: {path}"
        )
    if last_totals is None:
        raise CodexSessionUsageError(
            f"codex session rollout has no token_count usage events: {path}"
        )
    if not model:
        raise CodexSessionUsageError(
            f"codex session rollout has no turn_context model id: {path}"
        )

    duration_ms: int | None = None
    observed_at = _parse_timestamp(last_totals_at)
    if session_started_at is not None and observed_at is not None:
        elapsed_seconds = (observed_at - session_started_at).total_seconds()
        if elapsed_seconds >= 0:
            duration_ms = int(elapsed_seconds * 1000)

    observation: dict[str, Any] = {
        "input_tokens": last_totals.get("input_tokens"),
        "output_tokens": last_totals.get("output_tokens"),
        "cache_tokens": last_totals.get("cached_input_tokens"),
        "provider": CODEX_USAGE_PROVIDER,
        "model": model,
        "session_id": session_id,
        "source_snapshot_id": f"codex:{session_id}:{last_totals_at or 'unanchored'}",
        "measurement_kind": "absolute",
    }
    if duration_ms is not None:
        observation["duration_ms"] = duration_ms
    return observation


def usage_snapshot_path(runs_dir: Path) -> Path:
    return Path(runs_dir) / USAGE_SNAPSHOT_FILENAME


def load_usage_snapshot(runs_dir: Path) -> dict[str, Any] | None:
    """Return the persisted per-session cumulative baselines, if any.

    A missing snapshot means no session has been booked yet, so any session's
    first observation is an absolute intake. A corrupt or unknown-schema
    snapshot fails closed instead of silently rebasing spend; the file is
    private per-goal state and may be deleted to restart absolute intake.
    """
    path = usage_snapshot_path(runs_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CodexSessionUsageError(f"usage snapshot state is unreadable: {path}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexSessionUsageError(f"usage snapshot state is corrupt: {path}") from exc
    if (
        not isinstance(data, dict)
        or str(data.get("schema_version") or "") != USAGE_SNAPSHOT_SCHEMA_VERSION
        or not isinstance(data.get("sessions"), dict)
    ):
        raise CodexSessionUsageError(f"usage snapshot state has an unknown schema: {path}")
    return data


def store_usage_snapshot(runs_dir: Path, observation: Mapping[str, Any]) -> Path:
    """Persist the observation as its own session's next delta basis.

    Baselines are grouped by session id: a single shared slot would be
    overwritten by an interleaved session, making a returning session look
    brand new and re-booking its full cumulative total as fresh spend. Each
    entry keeps every counter and binding label (not only the id) so replay
    of the same identity can be verified field by field.
    """
    session_id = str(observation.get("session_id") or "").strip()
    if not session_id:
        raise CodexSessionUsageError("usage observation has no session id to persist")
    state = load_usage_snapshot(runs_dir) or {
        "schema_version": USAGE_SNAPSHOT_SCHEMA_VERSION,
        "sessions": {},
    }
    record: dict[str, Any] = {}
    for field in _SNAPSHOT_FIELDS:
        record[field] = observation.get(field)
    state["sessions"][session_id] = record
    path = usage_snapshot_path(runs_dir)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp_path.replace(path)
    return path


def previous_snapshot_for_observation(
    snapshot: Mapping[str, Any] | None,
    observation: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Return the stored delta basis for the observation's own session.

    Each Codex session counts cumulatively from zero, so the basis must come
    from the same session: a new session's first observation is an absolute
    intake, and a returning session rebases against its own last accepted
    snapshot even when other sessions were booked in between.
    """
    if snapshot is None:
        return None
    sessions = snapshot.get("sessions")
    if not isinstance(sessions, Mapping):
        return None
    basis = sessions.get(str(observation.get("session_id") or ""))
    return basis if isinstance(basis, Mapping) else None
