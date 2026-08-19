"""Public-safe repo-health snapshot contract.

The snapshot only contains public repository metrics. It never accepts or
emits raw trajectories, benchmark evidence, credentials, or private links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SNAPSHOT_SCHEMA_VERSION = "repo_health_snapshot_v0"


@dataclass
class RepoHealthSnapshot:
    captured_at: str
    repo: dict[str, Any]
    counts: dict[str, int]
    traffic_14d: dict[str, dict[str, int]]
    latency: dict[str, float | None]
    star_timeline_weekly: list[dict[str, Any]]
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "captured_at": self.captured_at,
            "repo": self.repo,
            "counts": self.counts,
            "traffic_14d": self.traffic_14d,
            "latency": self.latency,
            "star_timeline_weekly": self.star_timeline_weekly,
            "evidence": self.evidence,
        }


def validate_snapshot(payload: dict[str, Any]) -> list[str]:
    """Return a list of contract violations (empty when the payload is valid)."""

    violations: list[str] = []
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        violations.append(f"schema_version must be {SNAPSHOT_SCHEMA_VERSION}")
    for key in ("captured_at", "repo", "counts", "traffic_14d", "latency", "star_timeline_weekly"):
        if key not in payload:
            violations.append(f"missing required field {key}")
    counts = payload.get("counts")
    if not isinstance(counts, dict):
        violations.append("counts must be an object")
    else:
        for metric in (
            "stars",
            "forks",
            "watchers",
            "open_issues",
            "releases",
            "contributors",
            "prs_total",
            "issues_total",
        ):
            if not isinstance(counts.get(metric), int) or counts[metric] < 0:
                violations.append(f"counts.{metric} must be a non-negative integer")
    traffic = payload.get("traffic_14d")
    if isinstance(traffic, dict):
        for surface in ("views", "clones", "docs_views"):
            item = traffic.get(surface)
            if not isinstance(item, dict) or not all(
                isinstance(item.get(k), int) and item[k] >= 0 for k in ("count", "uniques")
            ):
                violations.append(f"traffic_14d.{surface} must have non-negative count/uniques")
        paths = traffic.get("paths")
        if not isinstance(paths, list):
            violations.append("traffic_14d.paths must be an array")
        else:
            for row in paths:
                if not isinstance(row, dict):
                    violations.append("traffic_14d.paths rows must be objects")
                    continue
                for key in ("path", "title"):
                    if not isinstance(row.get(key), str):
                        violations.append(f"traffic_14d.paths row {key} must be a string")
                for key in ("count", "uniques"):
                    if not isinstance(row.get(key), int) or row[key] < 0:
                        violations.append(f"traffic_14d.paths row {key} must be a non-negative integer")
    else:
        violations.append("traffic_14d must be an object")
    latency = payload.get("latency")
    if not isinstance(latency, dict):
        violations.append("latency must be an object")
    return violations
