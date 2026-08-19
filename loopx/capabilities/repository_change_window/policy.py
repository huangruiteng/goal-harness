from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import IntEnum
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


POLICY_SCHEMA_VERSION = "repository_change_window_policy_v0"
DECISION_SCHEMA_VERSION = "repository_change_window_decision_v0"


class ChangeWindowPolicyError(ValueError):
    """A fail-closed repository change-window policy error."""


class Weekday(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    @property
    def token(self) -> str:
        return (
            "mon",
            "tue",
            "wed",
            "thu",
            "fri",
            "sat",
            "sun",
        )[int(self)]

    @classmethod
    def parse(cls, value: str) -> Weekday:
        normalized = str(value or "").strip().lower()
        aliases = {
            "mon": cls.MONDAY,
            "monday": cls.MONDAY,
            "tue": cls.TUESDAY,
            "tuesday": cls.TUESDAY,
            "wed": cls.WEDNESDAY,
            "wednesday": cls.WEDNESDAY,
            "thu": cls.THURSDAY,
            "thursday": cls.THURSDAY,
            "fri": cls.FRIDAY,
            "friday": cls.FRIDAY,
            "sat": cls.SATURDAY,
            "saturday": cls.SATURDAY,
            "sun": cls.SUNDAY,
            "sunday": cls.SUNDAY,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ChangeWindowPolicyError(
                f"unsupported weekday `{value}`; use mon through sun"
            ) from exc


def parse_local_time(value: str) -> time:
    normalized = str(value or "").strip()
    try:
        parsed = time.fromisoformat(normalized)
    except ValueError as exc:
        raise ChangeWindowPolicyError(
            f"invalid local time `{value}`; use HH:MM"
        ) from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ChangeWindowPolicyError("local times must use minute precision HH:MM")
    return parsed


def _format_local_time(value: time) -> str:
    return value.strftime("%H:%M")


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute


def _window_blocks_week_minute(
    window: BlockedWindow,
    *,
    weekday: Weekday,
    minute: int,
) -> bool:
    start = _minute_of_day(window.start_local)
    end = _minute_of_day(window.end_local)
    if not window.crosses_midnight:
        return weekday in window.weekdays and start <= minute < end
    previous_weekday = Weekday((int(weekday) - 1) % 7)
    return (weekday in window.weekdays and minute >= start) or (
        previous_weekday in window.weekdays and minute < end
    )


def _has_eligible_week_minute(windows: Sequence[BlockedWindow]) -> bool:
    return any(
        not any(
            _window_blocks_week_minute(
                window,
                weekday=Weekday(weekday),
                minute=minute,
            )
            for window in windows
        )
        for weekday in range(7)
        for minute in range(24 * 60)
    )


@dataclass(frozen=True, slots=True)
class BlockedWindow:
    weekdays: tuple[Weekday, ...]
    start_local: time
    end_local: time

    def __post_init__(self) -> None:
        if not self.weekdays:
            raise ChangeWindowPolicyError(
                "a blocked window requires at least one weekday"
            )
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ChangeWindowPolicyError("blocked-window weekdays must be unique")
        if self.start_local == self.end_local:
            raise ChangeWindowPolicyError(
                "blocked-window start and end must differ; split full-day policies explicitly"
            )

    @property
    def crosses_midnight(self) -> bool:
        return self.end_local < self.start_local

    def to_dict(self) -> dict[str, Any]:
        return {
            "weekdays": [day.token for day in self.weekdays],
            "start_local": _format_local_time(self.start_local),
            "end_local": _format_local_time(self.end_local),
            "crosses_midnight": self.crosses_midnight,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BlockedWindow:
        weekdays = raw.get("weekdays")
        if not isinstance(weekdays, list) or not all(
            isinstance(item, str) for item in weekdays
        ):
            raise ChangeWindowPolicyError(
                "blocked-window weekdays must be a string list"
            )
        return cls(
            weekdays=tuple(Weekday.parse(item) for item in weekdays),
            start_local=parse_local_time(str(raw.get("start_local") or "")),
            end_local=parse_local_time(str(raw.get("end_local") or "")),
        )


@dataclass(frozen=True, slots=True)
class ChangeWindowPolicy:
    timezone_name: str
    blocked_windows: tuple[BlockedWindow, ...]

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ChangeWindowPolicyError(
                f"unknown IANA timezone `{self.timezone_name}`"
            ) from exc
        if not self.blocked_windows:
            raise ChangeWindowPolicyError("policy requires at least one blocked window")
        if not _has_eligible_week_minute(self.blocked_windows):
            raise ChangeWindowPolicyError(
                "policy must leave at least one eligible local minute per week"
            )

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": POLICY_SCHEMA_VERSION,
            "timezone": self.timezone_name,
            "strategy": "deny_during_local_windows",
            "blocked_windows": [window.to_dict() for window in self.blocked_windows],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ChangeWindowPolicy:
        if raw.get("schema_version") != POLICY_SCHEMA_VERSION:
            raise ChangeWindowPolicyError(f"policy must use `{POLICY_SCHEMA_VERSION}`")
        if raw.get("strategy") != "deny_during_local_windows":
            raise ChangeWindowPolicyError(
                "policy strategy must be `deny_during_local_windows`"
            )
        windows = raw.get("blocked_windows")
        if not isinstance(windows, list) or not all(
            isinstance(item, Mapping) for item in windows
        ):
            raise ChangeWindowPolicyError("blocked_windows must be an object list")
        return cls(
            timezone_name=str(raw.get("timezone") or ""),
            blocked_windows=tuple(BlockedWindow.from_dict(item) for item in windows),
        )


def build_policy(
    *,
    timezone_name: str,
    weekdays: Sequence[str],
    blocked_start: str,
    blocked_end: str,
) -> ChangeWindowPolicy:
    normalized_days = tuple(dict.fromkeys(Weekday.parse(day) for day in weekdays))
    return ChangeWindowPolicy(
        timezone_name=str(timezone_name or "").strip(),
        blocked_windows=(
            BlockedWindow(
                weekdays=normalized_days,
                start_local=parse_local_time(blocked_start),
                end_local=parse_local_time(blocked_end),
            ),
        ),
    )


def _interval(
    window: BlockedWindow,
    anchor: date,
    *,
    zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    start = datetime.combine(anchor, window.start_local, tzinfo=zone)
    end_date = anchor + timedelta(days=1) if window.crosses_midnight else anchor
    end = datetime.combine(end_date, window.end_local, tzinfo=zone)
    return start, end


def _covering_intervals(
    policy: ChangeWindowPolicy,
    instant: datetime,
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []
    for offset in range(-1, 9):
        anchor = instant.date() + timedelta(days=offset)
        for window in policy.blocked_windows:
            if Weekday(anchor.weekday()) not in window.weekdays:
                continue
            start, end = _interval(window, anchor, zone=policy.zone)
            if start <= instant < end:
                intervals.append((start, end))
    return intervals


def evaluate_policy(
    policy: ChangeWindowPolicy,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = now if now is not None else datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ChangeWindowPolicyError(
            "policy evaluation requires a timezone-aware clock"
        )
    local_now = observed.astimezone(policy.zone)
    covering = _covering_intervals(policy, local_now)
    if not covering:
        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "allowed": True,
            "reason": "outside_blocked_window",
            "timezone": policy.timezone_name,
            "observed_at": local_now.isoformat(),
            "next_eligible_at": local_now.isoformat(),
        }

    eligible = max(end for _start, end in covering)
    while True:
        chained = _covering_intervals(policy, eligible)
        later = [end for _start, end in chained if end > eligible]
        if not later:
            break
        eligible = max(later)
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "allowed": False,
        "reason": "inside_blocked_window",
        "timezone": policy.timezone_name,
        "observed_at": local_now.isoformat(),
        "next_eligible_at": eligible.isoformat(),
    }
