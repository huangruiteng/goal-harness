from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

CATALOG_SCHEMA_VERSION = "codex_provider_routing_catalog_v1"
REQUEST_SCHEMA_VERSION = "loopx_codex_provider_routing_request_v0"
RESPONSE_SCHEMA_VERSION = "loopx_codex_provider_routing_response_v0"

FORBIDDEN_KEYS = {
    "api_key",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
ALLOWED_MODALITIES = {"text", "image"}
ALLOWED_PROVIDERS = {"codex", "openai_compatibility"}
ALLOWED_REASONING_LEVELS = {"low", "medium", "high", "xhigh", "max", "ultra"}
SYMBOLIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MODEL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9./-]{0,127}$")
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?:^|\s)/(?:Users|home|var/folders)/"),
    re.compile("codex" + r"://threads/", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE),
    re.compile(r"\b" + "sk-" + r"[A-Za-z0-9_-]{12,}"),
)


def reject_private_material(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"credential-like field forbidden at {path}.{key}")
            reject_private_material(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_private_material(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"private-looking string forbidden at {path}")


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string list")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must not contain duplicates")
    return list(value)


def _boolean(value: Any, field: str, *, default: bool | None = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    return value


def _compile_profiles(raw_profiles: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("profiles must be a non-empty list")
    profiles: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_profiles):
        if not isinstance(raw, Mapping):
            raise TypeError(f"profiles[{index}] must be an object")
        profile_id = _non_empty_string(raw.get("id"), f"profiles[{index}].id")
        if SYMBOLIC_ID_RE.fullmatch(profile_id) is None:
            raise ValueError(f"profile id must be a public symbolic id: {profile_id}")
        if profile_id in profiles:
            raise ValueError(f"duplicate profile id: {profile_id}")
        provider = _non_empty_string(raw.get("provider"), f"profiles[{index}].provider")
        if provider not in ALLOWED_PROVIDERS:
            raise ValueError(f"unsupported provider for {profile_id}: {provider}")
        priority = raw.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError(f"profile {profile_id} needs integer priority")
        modalities = _string_list(
            raw.get("input_modalities"), f"profiles[{index}].input_modalities"
        )
        if not modalities or not set(modalities) <= ALLOWED_MODALITIES:
            raise ValueError(f"profile {profile_id} has unsupported input modalities")
        profiles[profile_id] = {
            "id": profile_id,
            "provider": provider,
            "priority": priority,
            "input_modalities": modalities,
            "supports_fast": _boolean(
                raw.get("supports_fast"),
                f"profiles[{index}].supports_fast",
                default=False,
            ),
        }
    return profiles


def _eligible_profiles(
    candidates: Sequence[str],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    required_modalities: set[str],
    require_fast: bool = False,
) -> list[str]:
    eligible: list[str] = []
    for profile_id in candidates:
        profile = profiles[profile_id]
        if not required_modalities <= set(profile["input_modalities"]):
            continue
        if require_fast and not profile["supports_fast"]:
            continue
        eligible.append(profile_id)
    return eligible


def compile_catalog(source: Mapping[str, Any]) -> dict[str, Any]:
    reject_private_material(source)
    profiles = _compile_profiles(source.get("profiles"))
    raw_routes = source.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("routes must be a non-empty list")

    routes: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    for index, raw in enumerate(raw_routes):
        if not isinstance(raw, Mapping):
            raise TypeError(f"routes[{index}] must be an object")
        slug = _non_empty_string(raw.get("slug"), f"routes[{index}].slug")
        if MODEL_SLUG_RE.fullmatch(slug) is None:
            raise ValueError(f"route slug must be a public model id: {slug}")
        if slug in route_ids:
            raise ValueError(f"duplicate route slug: {slug}")
        route_ids.add(slug)
        mode = _non_empty_string(raw.get("mode"), f"routes[{index}].mode")
        if mode not in {"auto", "manual", "alias"}:
            raise ValueError(f"route {slug} has unsupported mode: {mode}")
        visible = _boolean(raw.get("visible"), f"routes[{index}].visible", default=True)
        display_name = _non_empty_string(
            raw.get("display_name"), f"routes[{index}].display_name"
        )
        declared_modalities = _string_list(
            raw.get("input_modalities"), f"routes[{index}].input_modalities"
        )
        if (
            not declared_modalities
            or not set(declared_modalities) <= ALLOWED_MODALITIES
        ):
            raise ValueError(f"route {slug} has unsupported input modalities")
        reasoning = _string_list(
            raw.get("reasoning_levels", []), f"routes[{index}].reasoning_levels"
        )
        if not set(reasoning) <= ALLOWED_REASONING_LEVELS:
            raise ValueError(f"route {slug} has unsupported reasoning levels")

        candidates = _string_list(
            raw.get("candidates", []), f"routes[{index}].candidates"
        )
        for profile_id in candidates:
            if profile_id not in profiles:
                raise ValueError(
                    f"route {slug} references unknown profile: {profile_id}"
                )
        if mode == "manual" and len(candidates) != 1:
            raise ValueError(f"manual route must pin exactly one profile: {slug}")
        if mode == "auto" and len(candidates) < 2:
            raise ValueError(f"auto route needs at least two candidates: {slug}")
        if mode == "alias" and candidates:
            raise ValueError(f"alias route must not declare candidates: {slug}")

        alias_for = raw.get("alias_for")
        if mode == "alias":
            alias_for = _non_empty_string(alias_for, f"routes[{index}].alias_for")
        elif alias_for is not None:
            raise ValueError(f"non-alias route must not set alias_for: {slug}")

        if mode != "alias":
            priorities = [profiles[profile_id]["priority"] for profile_id in candidates]
            if mode == "auto" and any(
                current <= following for current, following in pairwise(priorities)
            ):
                raise ValueError(f"auto route priorities must strictly descend: {slug}")
            for modality in declared_modalities:
                if not _eligible_profiles(
                    candidates, profiles, required_modalities={modality}
                ):
                    raise ValueError(
                        f"route {slug} has no eligible candidate for modality {modality}"
                    )

        supports_fast = _boolean(
            raw.get("supports_fast"),
            f"routes[{index}].supports_fast",
            default=False,
        )
        if (
            supports_fast
            and mode != "alias"
            and not _eligible_profiles(
                candidates,
                profiles,
                required_modalities=set(declared_modalities),
                require_fast=True,
            )
        ):
            raise ValueError(f"route {slug} has no fast-eligible candidate")

        routes.append(
            {
                "slug": slug,
                "display_name": display_name,
                "visibility": "visible" if visible else "hidden",
                "routing_mode": mode,
                "alias_for": alias_for,
                "input_modalities": declared_modalities,
                "reasoning_levels": reasoning,
                "candidates": candidates,
                "eligible_candidates": {
                    modality: _eligible_profiles(
                        candidates, profiles, required_modalities={modality}
                    )
                    for modality in declared_modalities
                }
                if mode != "alias"
                else {},
                "supports_fast": supports_fast,
                "fast_candidates": _eligible_profiles(
                    candidates,
                    profiles,
                    required_modalities=set(declared_modalities),
                    require_fast=True,
                )
                if supports_fast and mode != "alias"
                else [],
                "routing_policy": {
                    "candidate_filter": "required_modalities_and_service_tier",
                    "on_no_eligible_provider": "fail_closed_before_first_output",
                    "session_affinity": "hint_revalidated_per_attempt"
                    if mode == "auto"
                    else "disabled",
                    "commit_barrier": "before_first_visible_output_or_tool_call",
                    "foreign_history": "normalize_or_quarantine",
                },
            }
        )

    aliases = [route for route in routes if route["routing_mode"] == "alias"]
    non_alias_routes = {
        route["slug"]: route for route in routes if route["routing_mode"] != "alias"
    }
    for alias in aliases:
        if alias["alias_for"] not in non_alias_routes:
            raise ValueError(
                f"alias {alias['slug']} references unknown route: {alias['alias_for']}"
            )
        target = non_alias_routes[alias["alias_for"]]
        if alias["input_modalities"] != target["input_modalities"]:
            raise ValueError(
                f"alias {alias['slug']} input modalities differ from target"
            )
        if alias["supports_fast"] != target["supports_fast"]:
            raise ValueError(f"alias {alias['slug']} Fast support differs from target")

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "credential_free": True,
        "default_service_tier": "default",
        "profiles": list(profiles.values()),
        "routes": routes,
    }


def qualify_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    reject_private_material(snapshot)
    expected_visible = {
        "auto/gpt-5.6-sol",
        "codex-a/gpt-5.6-sol",
        "codex-b/gpt-5.6-sol",
        "gpt-5.6-luna",
        "ark/deepseek-v4-flash",
    }
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"id": check_id, "passed": bool(passed), "detail": detail})

    visible = set(
        _string_list(snapshot.get("visible_models"), "snapshot.visible_models")
    )
    hidden = set(_string_list(snapshot.get("hidden_models"), "snapshot.hidden_models"))
    check(
        "visible_routes",
        visible == expected_visible,
        "selector exposes exactly Auto/A/B/Luna/Ark",
    )
    check(
        "hidden_alias",
        "gpt-5.6-sol" in hidden,
        "bare compatibility alias remains hidden",
    )
    modalities = snapshot.get("input_modalities")
    if not isinstance(modalities, Mapping):
        raise TypeError("snapshot.input_modalities must be an object")
    check(
        "codex_image_admission",
        all(
            set(modalities.get(slug, [])) == {"text", "image"}
            for slug in (
                "auto/gpt-5.6-sol",
                "codex-a/gpt-5.6-sol",
                "codex-b/gpt-5.6-sol",
                "gpt-5.6-luna",
            )
        ),
        "Auto/A/B/Luna declare text and image",
    )
    check(
        "ark_text_only",
        set(modalities.get("ark/deepseek-v4-flash", [])) == {"text"},
        "Ark remains text-only",
    )
    fast_models = set(_string_list(snapshot.get("fast_models"), "snapshot.fast_models"))
    check(
        "fast_projection",
        fast_models
        == {
            "auto/gpt-5.6-sol",
            "codex-a/gpt-5.6-sol",
            "codex-b/gpt-5.6-sol",
            "gpt-5.6-luna",
        },
        "Fast is exposed only for Auto/A/B/Luna",
    )
    check(
        "fast_default_off",
        snapshot.get("default_service_tier") == "default",
        "Fast is available but defaults to off",
    )
    check(
        "loopback_endpoint",
        snapshot.get("endpoint_host") in {"127.0.0.1", "localhost"},
        "CPA endpoint is loopback-only",
    )
    check(
        "modality_aware_affinity",
        snapshot.get("affinity_policy") == "hint_revalidated_per_attempt",
        "Auto affinity is revalidated against required modalities per attempt",
    )
    check(
        "settings_revision",
        snapshot.get("settings_revision_durable") is True
        and snapshot.get("turn_revision_matches") is True,
        "new turn uses a durable settings revision",
    )
    check(
        "commit_barrier",
        snapshot.get("commit_barrier") == "before_first_visible_output_or_tool_call",
        "transparent failover ends before visible output or tool call",
    )
    return {
        "qualified": all(item["passed"] for item in checks),
        "checks": checks,
    }


def build_upgrade_plan(upgrade: Mapping[str, Any]) -> dict[str, Any]:
    reject_private_material(upgrade)
    current = _non_empty_string(upgrade.get("current_ref"), "upgrade.current_ref")
    target = _non_empty_string(upgrade.get("target_ref"), "upgrade.target_ref")
    changed_seams = _string_list(upgrade.get("changed_seams"), "upgrade.changed_seams")
    allowed_seams = {
        "history_projection",
        "sse_lifecycle",
        "retry_policy",
        "transport_pool",
        "model_catalog",
        "ssh_bridge",
        "modality_routing",
        "settings_revision",
    }
    unknown = sorted(set(changed_seams) - allowed_seams)
    if unknown:
        raise ValueError(f"unsupported changed seams: {unknown}")
    matrix = ["public_boundary", "doctor", "catalog_readback", "rollback_receipt"]
    seam_checks = {
        "history_projection": [
            "additional_tools",
            "foreign_reasoning",
            "tool_causality",
        ],
        "sse_lifecycle": ["unique_terminal", "active_item_pairing"],
        "retry_policy": ["bounded_attempts", "ttfb_p50_p95", "commit_barrier"],
        "transport_pool": [
            "h2_reuse",
            "tls_resumption",
            "draining_rebuild",
            "no_replay",
        ],
        "model_catalog": ["visible_routes", "hidden_alias", "fast_default_off"],
        "ssh_bridge": ["loopback_binds", "reconnect", "existing_task_resume"],
        "modality_routing": ["image_a_b", "ark_text_only", "no_eligible_fail_closed"],
        "settings_revision": [
            "durable_readback",
            "turn_revision_match",
            "old_turn_isolation",
        ],
    }
    for seam in changed_seams:
        matrix.extend(seam_checks[seam])
    return {
        "current_ref": current,
        "target_ref": target,
        "changed_seams": changed_seams,
        "steps": [
            "capture_private_operator_snapshot",
            "build_target_in_isolation",
            "run_public_safe_doctor",
            "run_changed_seam_matrix",
            "switch_operator_owned_pointer",
            "read_back_catalog_and_runtime",
            "retain_previous_pointer_for_rollback",
        ],
        "required_checks": list(dict.fromkeys(matrix)),
        "rollback_trigger": "any_failed_check_or_unexplained_regression",
    }
