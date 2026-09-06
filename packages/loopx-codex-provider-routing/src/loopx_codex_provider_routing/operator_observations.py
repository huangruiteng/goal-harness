"""Reduce local CPA observations to credential-free symbolic account status."""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any

from .selectors import MODEL_FAMILIES, SLOTS

GPT_MODEL = "gpt-5.6-sol"
LUNA_MODEL = "gpt-5.6-luna"


def utc_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if re.fullmatch("\\d+(?:\\.\\d+)?", raw):
            parsed = dt.datetime.fromtimestamp(float(raw), tz=dt.timezone.utc)
        else:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            parsed = parsed.astimezone(dt.timezone.utc)
    except (OverflowError, ValueError):
        return None
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def quota_projection(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    observed_at = utc_timestamp(raw.get("observed_at"))
    signals = raw.get("signals")
    if observed_at is None or not isinstance(signals, dict):
        return None
    normalized = {
        str(key).strip().lower(): str(value).strip()
        for (key, value) in signals.items()
        if str(key).strip() and str(value).strip()
    }
    prefixes = sorted(
        {
            key.removesuffix("-used-percent")
            for key in normalized
            if key.startswith("x-codex-") and key.endswith("-used-percent")
        }
    )
    windows: list[dict[str, Any]] = []
    for prefix in prefixes:
        try:
            used = float(normalized[prefix + "-used-percent"])
            minutes = int(float(normalized[prefix + "-window-minutes"]))
        except (KeyError, ValueError):
            continue
        if not 0 <= used <= 100 or minutes <= 0:
            continue
        window_id = re.sub("[^a-z0-9-]+", "-", prefix.removeprefix("x-codex-"))
        window_id = window_id.strip("-")[:64]
        if not window_id:
            continue
        window: dict[str, Any] = {
            "id": window_id,
            "used_percent": used,
            "window_minutes": minutes,
        }
        reset_at = utc_timestamp(normalized.get(prefix + "-reset-at"))
        if reset_at is None:
            try:
                seconds = float(normalized[prefix + "-reset-after-seconds"])
                base = dt.datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                reset_at = (
                    (base + dt.timedelta(seconds=seconds))
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z")
                )
            except (KeyError, ValueError):
                pass
        if reset_at is not None:
            window["reset_at"] = reset_at
        windows.append(window)
    return {"observed_at": observed_at, "windows": windows}


class ObservationMixin:
    def account_observations(self) -> list[dict[str, Any]]:
        slots = self.load_slots()
        by_name = {
            str(item.get("name")): item
            for item in self.fetch_management_auth_files()
            if isinstance(item.get("name"), str)
        }
        observations: list[dict[str, Any]] = []
        for slot in SLOTS:
            name = slots.get(slot)
            entry = by_name.get(name, {}) if name else {}
            if entry.get("disabled") or entry.get("unavailable"):
                state = "unavailable"
            elif str(entry.get("status", "")).lower() in {"active", "ready"}:
                state = "ready"
            elif entry:
                state = "degraded"
            else:
                state = "unknown"
            recent = entry.get("recent_requests")
            buckets = recent if isinstance(recent, list) else []
            success = sum(
                int(item.get("success", 0))
                for item in buckets
                if isinstance(item, dict)
                and isinstance(item.get("success", 0), (int, float))
            )
            failed = sum(
                int(item.get("failed", 0))
                for item in buckets
                if isinstance(item, dict)
                and isinstance(item.get("failed", 0), (int, float))
            )
            quota = quota_projection(entry.get("quota"))
            if quota is None:
                model_quotas = entry.get("model_quotas")
                if isinstance(model_quotas, dict):
                    candidates = [
                        quota_projection(model_quotas.get(model))
                        for model in (*MODEL_FAMILIES, LUNA_MODEL)
                    ]
                    candidates = [item for item in candidates if item is not None]
                    if candidates:
                        quota = max(candidates, key=lambda item: item["observed_at"])
            observations.append(
                {
                    "profile_id": f"codex-{slot}",
                    "state": state,
                    "quota": quota,
                    "recent_activity": {
                        "success": success,
                        "failed": failed,
                        "window_minutes": max(len(buckets), 1) * 10,
                    },
                }
            )
        return observations

    def _map_auth_to_profile(
        self, auth_value: str, slots: dict[str, str]
    ) -> str | None:
        for slot, name in slots.items():
            if auth_value == name or auth_value.endswith("auth_file=" + name):
                return f"codex-{slot}"
        if auth_value.startswith("openai-compatibility:"):
            return "ark-text"
        return None

    def latest_execution_observation(
        self, *, modality: str = "text", fast: bool = False
    ) -> dict[str, Any]:
        log_path = next((path for path in self.LOG_CANDIDATES if path.is_file()), None)
        if log_path is None:
            raise RuntimeError("CPA runtime log is unavailable")
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 16 * 1024 * 1024))
            text = handle.read().decode("utf-8", errors="replace")
        line_re = re.compile(
            "^\\[(?P<time>[^]]+)] \\[(?P<request>[0-9a-f]{8})] \\[[^]]+] \\[(?P<source>[^]]+)].*$"
        )
        selector_re = re.compile("\\bauth=(?P<auth>\\S+).*\\bmodel=(?P<model>\\S+)")
        terminal_re = re.compile(
            '\\]\\s+(?P<status>\\d{3})\\s+\\|.*POST\\s+\\"/v1/responses\\"'
        )
        slots = self.load_slots()
        attempts: dict[str, list[str]] = {}
        routes: dict[str, str] = {}
        latest: dict[str, Any] | None = None
        for line in text.splitlines():
            match = line_re.match(line)
            if match is None:
                continue
            request_id = match.group("request")
            if "selector.go:" in match.group("source"):
                selected = selector_re.search(line)
                if selected is None:
                    continue
                profile = self._map_auth_to_profile(selected.group("auth"), slots)
                if profile is None:
                    continue
                chain = attempts.setdefault(request_id, [])
                if not chain or chain[-1] != profile:
                    chain.append(profile)
                routes[request_id] = selected.group("model")
                continue
            if "gin_logger.go:" not in match.group("source"):
                continue
            terminal = terminal_re.search(line)
            if (
                terminal is None
                or request_id not in attempts
                or request_id not in routes
            ):
                continue
            status_code = int(terminal.group("status"))
            observed = utc_timestamp(
                dt.datetime.fromisoformat(match.group("time")).astimezone().isoformat()
            )
            if observed is None:
                continue
            chain = attempts[request_id]
            outcome = "success" if 200 <= status_code < 300 else "failed"
            route_slug = routes[request_id]
            latest = {
                "route_slug": route_slug,
                "modality": modality,
                "fast": route_slug.startswith("fast/"),
                "observed_at": observed,
                "attempted_profiles": chain,
                "selected_profile": chain[-1] if outcome == "success" else None,
                "outcome": outcome,
            }
        if latest is None:
            raise RuntimeError("no completed CPA route observation was found")
        if latest["selected_profile"] is None:
            latest.pop("selected_profile")
        return latest
