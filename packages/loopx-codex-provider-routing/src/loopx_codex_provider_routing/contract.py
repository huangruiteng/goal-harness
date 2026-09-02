from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

CATALOG_SCHEMA_VERSION = "codex_provider_routing_catalog_v1"
RUNTIME_STATUS_SCHEMA_VERSION = "codex_provider_routing_runtime_status_v0"
REQUEST_SCHEMA_VERSION = "loopx_codex_provider_routing_request_v0"
RESPONSE_SCHEMA_VERSION = "loopx_codex_provider_routing_response_v0"
INTEGRATION_CANDIDATE_SCHEMA_VERSION = "codex_provider_integration_candidate_v0"
HEARTBEAT_TRANSPORT_SCHEMA_VERSION = "codex_app_heartbeat_transport_qualification_v0"

FORBIDDEN_KEYS = {
    "account_id",
    "api_key",
    "access_token",
    "auth_file",
    "auth_index",
    "refresh_token",
    "authorization",
    "cookie",
    "email",
    "filename",
    "password",
    "project_id",
    "secret",
    "session_id",
    "task_id",
    "token",
}
ALLOWED_MODALITIES = {"text", "image"}
ALLOWED_PROVIDERS = {"codex", "openai_compatibility"}
ALLOWED_REASONING_LEVELS = {"low", "medium", "high", "xhigh", "max", "ultra"}
ALLOWED_CHANGE_SEAMS = {
    "history_projection",
    "integration_candidate",
    "modality_routing",
    "model_catalog",
    "request_normalizer",
    "retry_policy",
    "route_fallback",
    "settings_revision",
    "sse_lifecycle",
    "ssh_bridge",
    "transport_pool",
}
SYMBOLIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MODEL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9./-]{0,127}$")
GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
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


def qualify_heartbeat_transport(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Check the host boundary used to inject one scheduled heartbeat turn."""

    reject_private_material(observation)
    _reject_unexpected_keys(
        observation,
        {"turn_trigger", "payload_kind", "delivery_kind", "message_role", "tool_name"},
        "heartbeat_transport",
    )
    turn_trigger = _non_empty_string(
        observation.get("turn_trigger"), "heartbeat_transport.turn_trigger"
    )
    if turn_trigger != "automation_heartbeat":
        raise ValueError(
            "heartbeat_transport.turn_trigger must be automation_heartbeat"
        )
    payload_kind = _non_empty_string(
        observation.get("payload_kind"), "heartbeat_transport.payload_kind"
    )
    if payload_kind != "heartbeat_xml":
        raise ValueError("heartbeat_transport.payload_kind must be heartbeat_xml")
    delivery_kind = _non_empty_string(
        observation.get("delivery_kind"), "heartbeat_transport.delivery_kind"
    )
    if delivery_kind not in {"user_input", "tool_output"}:
        raise ValueError(
            "heartbeat_transport.delivery_kind must be user_input or tool_output"
        )

    message_role = observation.get("message_role")
    tool_name = observation.get("tool_name")
    if delivery_kind == "user_input":
        if message_role != "user":
            raise ValueError("heartbeat user_input must declare message_role=user")
        if tool_name is not None:
            raise ValueError("heartbeat user_input must not declare tool_name")
        qualified = True
        failure_code = None
    else:
        if message_role is not None:
            raise ValueError("heartbeat tool_output must not declare message_role")
        tool_name = _non_empty_string(tool_name, "heartbeat_transport.tool_name")
        qualified = False
        failure_code = (
            "heartbeat_mislabeled_as_automation_tool_output"
            if tool_name == "automation_update"
            else "heartbeat_injected_as_tool_output"
        )

    return {
        "schema_version": HEARTBEAT_TRANSPORT_SCHEMA_VERSION,
        "qualified": qualified,
        "failure_code": failure_code,
        "required_delivery": {
            "delivery_kind": "user_input",
            "message_role": "user",
        },
        "observed_delivery": {
            "delivery_kind": delivery_kind,
            "message_role": message_role,
            "tool_name": tool_name,
        },
        "responsible_layer": "codex_app_heartbeat_transport",
        "prompt_or_model_remediation": False,
    }


def _reject_unexpected_keys(
    value: Mapping[str, Any], allowed: set[str], field: str
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ValueError(f"{field} has unsupported fields: {unexpected}")


def _git_ref(value: Any, field: str) -> str:
    ref = _non_empty_string(value, field)
    if (
        GIT_REF_RE.fullmatch(ref) is None
        or ".." in ref
        or "@{" in ref
        or ref.endswith(("/", ".", ".lock"))
    ):
        raise ValueError(f"{field} must be a bounded public Git ref")
    return ref


def _git_sha(value: Any, field: str) -> str:
    sha = _non_empty_string(value, field)
    if GIT_SHA_RE.fullmatch(sha) is None:
        raise ValueError(f"{field} must be a full lowercase Git SHA")
    return sha


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


def _compile_rings(
    raw_rings: Any, profiles: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    if raw_rings is None:
        return {}
    if not isinstance(raw_rings, list):
        raise TypeError("rings must be a list")
    rings: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_rings):
        if not isinstance(raw, Mapping):
            raise TypeError(f"rings[{index}] must be an object")
        ring_id = _non_empty_string(raw.get("id"), f"rings[{index}].id")
        if SYMBOLIC_ID_RE.fullmatch(ring_id) is None:
            raise ValueError(f"ring id must be a public symbolic id: {ring_id}")
        if ring_id in rings:
            raise ValueError(f"duplicate ring id: {ring_id}")
        members = _string_list(raw.get("members"), f"rings[{index}].members")
        if len(members) < 2:
            raise ValueError(f"ring {ring_id} needs at least two members")
        for profile_id in members:
            if profile_id not in profiles:
                raise ValueError(
                    f"ring {ring_id} references unknown profile: {profile_id}"
                )
        max_cycles = raw.get("max_cycles")
        if max_cycles != 1 or isinstance(max_cycles, bool):
            raise ValueError(f"ring {ring_id} must use exactly one cycle")
        rings[ring_id] = {
            "id": ring_id,
            "members": members,
            "max_cycles": max_cycles,
        }
    return rings


def _rotate_members(members: Sequence[str], entrypoint: str) -> list[str]:
    index = members.index(entrypoint)
    return list(members[index:]) + list(members[:index])


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
    rings = _compile_rings(source.get("rings"), profiles)
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
        if mode not in {"auto", "preferred", "manual", "alias"}:
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

        ring_id = raw.get("ring")
        uses_ring = ring_id is not None
        fallback_tail = _string_list(
            raw.get("fallback_tail", []), f"routes[{index}].fallback_tail"
        )
        entrypoint = raw.get("entrypoint")
        if uses_ring:
            ring_id = _non_empty_string(ring_id, f"routes[{index}].ring")
            if ring_id not in rings:
                raise ValueError(f"route {slug} references unknown ring: {ring_id}")
            if mode not in {"auto", "preferred"}:
                raise ValueError(f"route {slug} cannot use a ring in {mode} mode")
            if "candidates" in raw:
                raise ValueError(
                    f"ring route must derive candidates instead of declaring them: {slug}"
                )
            members = rings[ring_id]["members"]
            if entrypoint is None and mode == "auto":
                entrypoint = "affinity_then_first"
            else:
                entrypoint = _non_empty_string(
                    entrypoint, f"routes[{index}].entrypoint"
                )
            if entrypoint == "affinity_then_first":
                if mode != "auto":
                    raise ValueError(
                        f"preferred route needs an explicit ring member: {slug}"
                    )
                ring_candidates = list(members)
            elif entrypoint in members:
                ring_candidates = _rotate_members(members, entrypoint)
            else:
                raise ValueError(
                    f"route {slug} entrypoint is not a member of ring {ring_id}"
                )
            if set(fallback_tail) & set(members):
                raise ValueError(f"route {slug} fallback tail overlaps its ring")
            candidates = ring_candidates + fallback_tail
        else:
            if fallback_tail or entrypoint is not None:
                raise ValueError(
                    f"non-ring route must not declare entrypoint or fallback tail: {slug}"
                )
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
        if mode in {"auto", "preferred"} and len(candidates) < 2:
            raise ValueError(f"resilient route needs at least two candidates: {slug}")
        if mode == "preferred" and not uses_ring:
            raise ValueError(f"preferred route must reference a ring: {slug}")
        if mode == "alias" and candidates:
            raise ValueError(f"alias route must not declare candidates: {slug}")

        alias_for = raw.get("alias_for")
        if mode == "alias":
            alias_for = _non_empty_string(alias_for, f"routes[{index}].alias_for")
        elif alias_for is not None:
            raise ValueError(f"non-alias route must not set alias_for: {slug}")

        if mode != "alias":
            priorities = [profiles[profile_id]["priority"] for profile_id in candidates]
            if (
                mode == "auto"
                and not uses_ring
                and any(
                    current <= following for current, following in pairwise(priorities)
                )
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
        fast_selector = raw.get("fast_selector")
        compiled_fast_selector = None
        if fast_selector is not None:
            if not isinstance(fast_selector, Mapping):
                raise TypeError(f"routes[{index}].fast_selector must be an object")
            _reject_unexpected_keys(
                fast_selector,
                {"display_name", "fallback_policy"},
                f"routes[{index}].fast_selector",
            )
            if mode == "alias" or not visible:
                raise ValueError(
                    f"Fast selector requires a visible concrete route: {slug}"
                )
            if not supports_fast:
                raise ValueError(f"Fast selector requires Fast support: {slug}")
            fallback_policy = _non_empty_string(
                fast_selector.get("fallback_policy"),
                f"routes[{index}].fast_selector.fallback_policy",
            )
            if fallback_policy != "fast_capable_only":
                raise ValueError(
                    f"route {slug} Fast selector must fail closed to Fast-capable providers"
                )
            compiled_fast_selector = {
                "display_name": _non_empty_string(
                    fast_selector.get("display_name"),
                    f"routes[{index}].fast_selector.display_name",
                ),
                "fallback_policy": fallback_policy,
            }
        max_cycles = rings[ring_id]["max_cycles"] if isinstance(ring_id, str) else 1

        routes.append(
            {
                "slug": slug,
                "display_name": display_name,
                "visibility": "visible" if visible else "hidden",
                "routing_mode": mode,
                "alias_for": alias_for,
                "ring_id": ring_id,
                "entrypoint": entrypoint,
                "fallback_tail": fallback_tail,
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
                "fast_selector": compiled_fast_selector,
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
                    if mode in {"auto", "preferred"}
                    else "disabled",
                    "traversal": "one_ring_pass_then_tail"
                    if uses_ring
                    else "ordered_candidates_once",
                    "max_cycles": max_cycles,
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

    selector_rows: list[dict[str, Any]] = []
    for route in routes:
        target = (
            non_alias_routes[route["alias_for"]]
            if route["routing_mode"] == "alias"
            else route
        )
        selector_rows.append(
            {
                "slug": route["slug"],
                "route_slug": target["slug"],
                "display_name": route["display_name"],
                "visibility": route["visibility"],
                "input_modalities": route["input_modalities"],
                "reasoning_levels": route["reasoning_levels"],
                "candidates": target["candidates"],
                "default_service_tier": "default",
                "request_service_tier_action": "preserve",
                "fallback_policy": "route_default",
            }
        )
        fast_selector = route["fast_selector"]
        if fast_selector is None:
            continue
        selector_rows.append(
            {
                "slug": f"fast/{route['slug']}",
                "route_slug": route["slug"],
                "display_name": fast_selector["display_name"],
                "visibility": route["visibility"],
                "input_modalities": route["input_modalities"],
                "reasoning_levels": route["reasoning_levels"],
                "candidates": route["fast_candidates"],
                "default_service_tier": "fast",
                "request_service_tier_action": "force_priority",
                "fallback_policy": fast_selector["fallback_policy"],
            }
        )
    selector_slugs = [row["slug"] for row in selector_rows]
    if len(selector_slugs) != len(set(selector_slugs)):
        raise ValueError("generated Fast selector collides with a declared route slug")

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "credential_free": True,
        "default_service_tier": "default",
        "fast_selector_prefix": "fast/",
        "fast_request_service_tier": "priority",
        "profiles": list(profiles.values()),
        "rings": list(rings.values()),
        "routes": routes,
        "selector_rows": selector_rows,
    }


def normalize_selector_request(normalization: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one public selector before provider alias mapping or body handling."""

    reject_private_material(normalization)
    _reject_unexpected_keys(
        normalization,
        {"catalog_source", "model_selector", "service_tier"},
        "normalization",
    )
    source = normalization.get("catalog_source")
    if not isinstance(source, Mapping):
        raise TypeError("normalization.catalog_source must be an object")
    catalog = compile_catalog(source)
    selector_slug = _non_empty_string(
        normalization.get("model_selector"), "normalization.model_selector"
    )
    selectors = {row["slug"]: row for row in catalog["selector_rows"]}
    selector = selectors.get(selector_slug)
    if selector is None:
        raise ValueError(f"unknown model selector: {selector_slug}")

    requested_tier = normalization.get("service_tier")
    if requested_tier is not None:
        requested_tier = _non_empty_string(requested_tier, "normalization.service_tier")
        if requested_tier not in {"default", "priority"}:
            raise ValueError("normalization.service_tier must be default or priority")

    tier_action: dict[str, str] = {"action": selector["request_service_tier_action"]}
    if selector["request_service_tier_action"] == "force_priority":
        tier_action["value"] = catalog["fast_request_service_tier"]
    elif requested_tier is not None:
        tier_action["value"] = requested_tier

    effective_fast = (
        selector["default_service_tier"] == "fast"
        or requested_tier == catalog["fast_request_service_tier"]
    )
    eligible_candidates = selector["candidates"]
    fallback_policy = selector["fallback_policy"]
    if effective_fast:
        profiles = {item["id"]: item for item in catalog["profiles"]}
        eligible_candidates = _eligible_profiles(
            selector["candidates"],
            profiles,
            required_modalities=set(),
            require_fast=True,
        )
        if not eligible_candidates:
            raise ValueError(f"selector {selector_slug} has no Fast-capable candidates")
        fallback_policy = "fast_capable_only"

    return {
        "original_model_selector": selector_slug,
        "normalized_model_selector": selector["route_slug"],
        "default_service_tier": selector["default_service_tier"],
        "service_tier": tier_action,
        "fallback_policy": fallback_policy,
        "eligible_candidates": eligible_candidates,
    }


def _timestamp(value: Any, field: str) -> str:
    timestamp = _non_empty_string(value, field)
    if (
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", timestamp)
        is None
    ):
        raise ValueError(f"{field} must be an RFC 3339 UTC timestamp")
    return timestamp


def _percentage(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{field} must be a number")
    if not 0 <= value <= 100:
        raise ValueError(f"{field} must be between 0 and 100")
    return float(value)


def _quota_windows(raw: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise TypeError(f"{field} must be a list")
    windows: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise TypeError(f"{field}[{index}] must be an object")
        _reject_unexpected_keys(
            item,
            {"id", "used_percent", "window_minutes", "reset_at"},
            f"{field}[{index}]",
        )
        window_id = _non_empty_string(item.get("id"), f"{field}[{index}].id")
        if SYMBOLIC_ID_RE.fullmatch(window_id) is None:
            raise ValueError(f"{field}[{index}].id must be a symbolic id")
        if window_id in ids:
            raise ValueError(f"{field} has duplicate window id: {window_id}")
        ids.add(window_id)
        used = _percentage(item.get("used_percent"), f"{field}[{index}].used_percent")
        minutes = item.get("window_minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            raise ValueError(f"{field}[{index}].window_minutes must be positive")
        reset_at = item.get("reset_at")
        if reset_at is not None:
            reset_at = _timestamp(reset_at, f"{field}[{index}].reset_at")
        windows.append(
            {
                "id": window_id,
                "used_percent": used,
                "remaining_percent": 100.0 - used,
                "window_minutes": minutes,
                "reset_at": reset_at,
            }
        )
    return windows


def _eligible_route_order(
    route: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    modality: str,
    fast: bool,
) -> list[str]:
    return _eligible_profiles(
        route["candidates"],
        profiles,
        required_modalities={modality},
        require_fast=fast,
    )


def _legal_attempt_orders(
    route: Mapping[str, Any],
    rings: Mapping[str, Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    *,
    modality: str,
    fast: bool,
) -> list[list[str]]:
    eligible = _eligible_route_order(route, profiles, modality=modality, fast=fast)
    if route["entrypoint"] != "affinity_then_first":
        return [eligible]
    ring = rings[route["ring_id"]]
    eligible_ring = [item for item in ring["members"] if item in eligible]
    eligible_tail = [item for item in route["fallback_tail"] if item in eligible]
    if not eligible_ring:
        return [eligible_tail]
    return [
        _rotate_members(eligible_ring, entrypoint) + eligible_tail
        for entrypoint in eligible_ring
    ]


def project_runtime_status(status: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project content-free host, route and account observations."""

    reject_private_material(status)
    _reject_unexpected_keys(
        status,
        {
            "schema_version",
            "credential_free",
            "catalog_source",
            "host_identity",
            "execution_observation",
            "account_observations",
        },
        "status",
    )
    source = status.get("catalog_source")
    if not isinstance(source, Mapping):
        raise TypeError("status.catalog_source must be an object")
    catalog = compile_catalog(source)
    profiles = {item["id"]: item for item in catalog["profiles"]}
    rings = {item["id"]: item for item in catalog["rings"]}
    routes = {
        item["slug"]: item
        for item in catalog["routes"]
        if item["routing_mode"] != "alias"
    }
    selectors = {item["slug"]: item for item in catalog["selector_rows"]}

    host = status.get("host_identity")
    if not isinstance(host, Mapping):
        raise TypeError("status.host_identity must be an object")
    expected_host = {
        "state": "retained",
        "projection": "not_projected",
        "route_binding": "none",
    }
    if dict(host) != expected_host:
        raise ValueError(
            "host identity must be retained, not projected and independent of routing"
        )

    observation = status.get("execution_observation")
    if not isinstance(observation, Mapping):
        raise TypeError("status.execution_observation must be an object")
    _reject_unexpected_keys(
        observation,
        {
            "route_slug",
            "modality",
            "fast",
            "observed_at",
            "attempted_profiles",
            "selected_profile",
            "outcome",
        },
        "status.execution_observation",
    )
    selector_slug = _non_empty_string(
        observation.get("route_slug"), "status.execution_observation.route_slug"
    )
    selector = selectors.get(selector_slug)
    if selector is None:
        raise ValueError("execution observation must reference a catalog selector")
    route = routes[selector["route_slug"]]
    modality = _non_empty_string(
        observation.get("modality"), "status.execution_observation.modality"
    )
    if modality not in route["input_modalities"]:
        raise ValueError(f"selector {selector_slug} does not admit modality {modality}")
    selector_defaults_fast = selector["default_service_tier"] == "fast"
    fast = selector_defaults_fast
    if "fast" in observation:
        declared_fast = _boolean(
            observation.get("fast"), "status.execution_observation.fast"
        )
        if selector_defaults_fast and not declared_fast:
            raise ValueError("a Fast selector cannot report a non-Fast execution")
        fast = declared_fast
    observed_at = _timestamp(
        observation.get("observed_at"), "status.execution_observation.observed_at"
    )
    attempted = _string_list(
        observation.get("attempted_profiles"),
        "status.execution_observation.attempted_profiles",
    )
    if not attempted:
        raise ValueError("execution observation needs at least one attempted profile")
    legal_orders = _legal_attempt_orders(
        route, rings, profiles, modality=modality, fast=fast
    )
    matching_orders = [
        order for order in legal_orders if attempted == order[: len(attempted)]
    ]
    if not matching_orders:
        raise ValueError(
            f"attempted profiles are not a legal prefix for selector {selector_slug}"
        )
    outcome = _non_empty_string(
        observation.get("outcome"), "status.execution_observation.outcome"
    )
    if outcome not in {"success", "failed"}:
        raise ValueError("execution outcome must be success or failed")
    selected = observation.get("selected_profile")
    if outcome == "success":
        selected = _non_empty_string(
            selected, "status.execution_observation.selected_profile"
        )
        if selected != attempted[-1]:
            raise ValueError(
                "successful selection must equal the final attempted profile"
            )
    elif "selected_profile" in observation:
        raise ValueError("failed execution must not declare a selected profile")

    raw_accounts = status.get("account_observations")
    if not isinstance(raw_accounts, list):
        raise TypeError("status.account_observations must be a list")
    accounts: list[dict[str, Any]] = []
    account_ids: set[str] = set()
    for index, raw in enumerate(raw_accounts):
        field = f"status.account_observations[{index}]"
        if not isinstance(raw, Mapping):
            raise TypeError(f"{field} must be an object")
        _reject_unexpected_keys(
            raw,
            {"profile_id", "state", "quota", "recent_activity"},
            field,
        )
        profile_id = _non_empty_string(raw.get("profile_id"), f"{field}.profile_id")
        if profile_id in account_ids:
            raise ValueError(f"duplicate account observation: {profile_id}")
        if profile_id not in profiles or profiles[profile_id]["provider"] != "codex":
            raise ValueError(
                f"account observation must reference a Codex profile: {profile_id}"
            )
        account_ids.add(profile_id)
        state = _non_empty_string(raw.get("state"), f"{field}.state")
        if state not in {"ready", "degraded", "unavailable", "unknown"}:
            raise ValueError(f"unsupported account state: {state}")
        quota = raw.get("quota")
        projected_quota = None
        if quota is not None:
            if not isinstance(quota, Mapping):
                raise TypeError(f"{field}.quota must be an object")
            _reject_unexpected_keys(quota, {"observed_at", "windows"}, f"{field}.quota")
            projected_quota = {
                "observed_at": _timestamp(
                    quota.get("observed_at"), f"{field}.quota.observed_at"
                ),
                "windows": _quota_windows(
                    quota.get("windows", []), f"{field}.quota.windows"
                ),
            }
        activity = raw.get("recent_activity")
        if not isinstance(activity, Mapping):
            raise TypeError(f"{field}.recent_activity must be an object")
        _reject_unexpected_keys(
            activity,
            {"success", "failed", "window_minutes"},
            f"{field}.recent_activity",
        )
        projected_activity: dict[str, int] = {}
        for key in ("success", "failed", "window_minutes"):
            value = activity.get(key)
            minimum = 1 if key == "window_minutes" else 0
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(f"{field}.recent_activity.{key} is invalid")
            projected_activity[key] = value
        accounts.append(
            {
                "profile_id": profile_id,
                "state": state,
                "quota": projected_quota,
                "recent_activity": projected_activity,
            }
        )

    execution = {
        "observed_at": observed_at,
        "attempted_profiles": attempted,
        "outcome": outcome,
        "fallback_used": len(attempted) > 1,
    }
    if selected is not None:
        execution["selected_profile"] = selected

    return {
        "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
        "credential_free": True,
        "host_identity": expected_host,
        "route_intent": {
            "selector_slug": selector_slug,
            "route_slug": route["slug"],
            "routing_mode": route["routing_mode"],
            "modality": modality,
            "fast": fast,
            "legal_attempt_orders": legal_orders,
        },
        "execution": execution,
        "accounts": accounts,
    }


def qualify_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    reject_private_material(snapshot)
    expected_visible = {
        "auto/gpt-5.6-sol",
        "fast/auto/gpt-5.6-sol",
        "codex-a/gpt-5.6-sol",
        "fast/codex-a/gpt-5.6-sol",
        "codex-b/gpt-5.6-sol",
        "fast/codex-b/gpt-5.6-sol",
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
        "selector exposes Standard and Fast Sol rows plus Luna and Ark",
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
                "fast/auto/gpt-5.6-sol",
                "codex-a/gpt-5.6-sol",
                "fast/codex-a/gpt-5.6-sol",
                "codex-b/gpt-5.6-sol",
                "fast/codex-b/gpt-5.6-sol",
                "gpt-5.6-luna",
            )
        ),
        "Standard/Fast Sol selectors and Luna declare text and image",
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
            "fast/auto/gpt-5.6-sol",
            "fast/codex-a/gpt-5.6-sol",
            "fast/codex-b/gpt-5.6-sol",
        },
        "Fast is exposed only as explicit Auto/Prefer A/Prefer B sibling rows",
    )
    selector_tiers = snapshot.get("selector_default_service_tiers")
    if not isinstance(selector_tiers, Mapping):
        raise TypeError("snapshot.selector_default_service_tiers must be an object")
    standard_selectors = expected_visible - fast_models
    check(
        "fast_default_off",
        snapshot.get("default_service_tier") == "default"
        and all(selector_tiers.get(slug) == "default" for slug in standard_selectors)
        and all(selector_tiers.get(slug) == "fast" for slug in fast_models),
        "ordinary rows stay Standard while explicit Fast rows opt into Fast",
    )
    normalizer = snapshot.get("request_normalizer")
    check(
        "request_normalizer",
        isinstance(normalizer, Mapping)
        and normalizer.get("active") is True
        and normalizer.get("selector_prefix") == "fast/"
        and normalizer.get("fast_request_service_tier") == "priority"
        and normalizer.get("ordinary_selector_action") == "preserve"
        and normalizer.get("effective_priority_admission") == "fast_capable_only",
        "normalizer preserves ordinary tiers and constrains effective Fast requests",
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
    route_traversal = snapshot.get("route_traversal")
    if not isinstance(route_traversal, Mapping):
        raise TypeError("snapshot.route_traversal must be an object")
    expected_traversal = {
        "auto/gpt-5.6-sol": {
            "entrypoint": "affinity_then_first",
            "ordered_candidates": ["codex-a", "codex-b", "ark-text"],
            "fallback_tail": ["ark-text"],
        },
        "fast/auto/gpt-5.6-sol": {
            "entrypoint": "affinity_then_first",
            "ordered_candidates": ["codex-a", "codex-b"],
            "fallback_tail": [],
        },
        "codex-a/gpt-5.6-sol": {
            "entrypoint": "codex-a",
            "ordered_candidates": ["codex-a", "codex-b", "ark-text"],
            "fallback_tail": ["ark-text"],
        },
        "fast/codex-a/gpt-5.6-sol": {
            "entrypoint": "codex-a",
            "ordered_candidates": ["codex-a", "codex-b"],
            "fallback_tail": [],
        },
        "codex-b/gpt-5.6-sol": {
            "entrypoint": "codex-b",
            "ordered_candidates": ["codex-b", "codex-a", "ark-text"],
            "fallback_tail": ["ark-text"],
        },
        "fast/codex-b/gpt-5.6-sol": {
            "entrypoint": "codex-b",
            "ordered_candidates": ["codex-b", "codex-a"],
            "fallback_tail": [],
        },
        "gpt-5.6-luna": {
            "entrypoint": "affinity_then_first",
            "ordered_candidates": ["codex-a", "codex-b"],
            "fallback_tail": [],
        },
    }
    traversal_rows: dict[str, Mapping[str, Any]] = {}
    for slug in expected_traversal:
        raw_row = route_traversal.get(slug)
        if not isinstance(raw_row, Mapping):
            raise TypeError(f"snapshot.route_traversal[{slug}] must be an object")
        traversal_rows[slug] = raw_row
        _string_list(
            raw_row.get("ordered_candidates"),
            f"snapshot.route_traversal[{slug}].ordered_candidates",
        )
        _string_list(
            raw_row.get("fallback_tail"),
            f"snapshot.route_traversal[{slug}].fallback_tail",
        )
    check(
        "preferred_route_order",
        all(
            traversal_rows[slug].get("entrypoint") == expected["entrypoint"]
            and traversal_rows[slug].get("ordered_candidates")
            == expected["ordered_candidates"]
            for slug, expected in expected_traversal.items()
        ),
        "Standard/Fast Sol selectors and Luna use the expected ring entrypoint and order",
    )
    check(
        "terminal_fallback_tail",
        all(
            traversal_rows[slug].get("fallback_tail") == expected["fallback_tail"]
            for slug, expected in expected_traversal.items()
        ),
        "only Standard Sol routes append Ark; Fast and Luna have no heterogeneous tail",
    )
    check(
        "fast_capable_only",
        all(
            traversal_rows[slug].get("ordered_candidates")
            in (["codex-a", "codex-b"], ["codex-b", "codex-a"])
            and traversal_rows[slug].get("fallback_tail") == []
            for slug in fast_models
        ),
        "Fast rows remain inside the A/B Fast-capable ring",
    )
    check(
        "single_cycle_traversal",
        all(row.get("max_cycles") == 1 for row in traversal_rows.values()),
        "every resilient route traverses the account ring at most once",
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
    unknown = sorted(set(changed_seams) - ALLOWED_CHANGE_SEAMS)
    if unknown:
        raise ValueError(f"unsupported changed seams: {unknown}")
    matrix = ["public_boundary", "doctor", "catalog_readback", "rollback_receipt"]
    seam_checks = {
        "history_projection": [
            "additional_tools",
            "foreign_reasoning",
            "tool_causality",
        ],
        "integration_candidate": [
            "exact_base_head",
            "exact_ordered_source_heads",
            "required_seam_coverage",
            "integration_tree_receipt",
        ],
        "sse_lifecycle": ["unique_terminal", "active_item_pairing"],
        "retry_policy": ["bounded_attempts", "ttfb_p50_p95", "commit_barrier"],
        "transport_pool": [
            "h2_reuse",
            "tls_resumption",
            "draining_rebuild",
            "no_replay",
        ],
        "model_catalog": [
            "visible_routes",
            "hidden_alias",
            "fast_selector_rows",
            "fast_default_off",
        ],
        "request_normalizer": [
            "selector_prefix_capture",
            "priority_injection",
            "ordinary_selector_preserved",
            "effective_priority_admission",
            "fast_route_no_unsupported_fallback",
        ],
        "route_fallback": [
            "preferred_entrypoint_order",
            "single_ring_cycle",
            "terminal_tail_once",
        ],
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


def reconcile_integration_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Compare a public-safe multi-source candidate with its last sync receipt.

    This operation owns provider-specific source coverage and upgrade policy.
    It returns inputs for LoopX's core integration-branch capability instead of
    implementing Git fetch, merge, push, or deployment effects.
    """

    reject_private_material(candidate)
    _reject_unexpected_keys(
        candidate,
        {
            "base_ref",
            "integration_branch",
            "required_seams",
            "sources",
            "observed",
            "last_sync",
        },
        "integration",
    )
    base_ref = _git_ref(candidate.get("base_ref"), "integration.base_ref")
    integration_branch = _git_ref(
        candidate.get("integration_branch"), "integration.integration_branch"
    )
    required_seams = _string_list(
        candidate.get("required_seams"), "integration.required_seams"
    )
    if not required_seams:
        raise ValueError("integration.required_seams must not be empty")
    unknown_required = sorted(set(required_seams) - ALLOWED_CHANGE_SEAMS)
    if unknown_required:
        raise ValueError(f"unsupported required seams: {unknown_required}")

    raw_sources = candidate.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) < 2:
        raise ValueError("integration.sources needs at least two ordered sources")
    sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    source_refs: set[str] = set()
    covered_seams: set[str] = set()
    for index, raw in enumerate(raw_sources):
        field = f"integration.sources[{index}]"
        if not isinstance(raw, Mapping):
            raise TypeError(f"{field} must be an object")
        _reject_unexpected_keys(
            raw,
            {"id", "kind", "ref", "head_sha", "changed_seams"},
            field,
        )
        source_id = _non_empty_string(raw.get("id"), f"{field}.id")
        if SYMBOLIC_ID_RE.fullmatch(source_id) is None:
            raise ValueError(f"{field}.id must be a public symbolic id")
        if source_id in source_ids:
            raise ValueError(f"duplicate integration source id: {source_id}")
        source_ids.add(source_id)
        kind = _non_empty_string(raw.get("kind"), f"{field}.kind")
        if kind not in {"pull_request", "public_safe_patch"}:
            raise ValueError(f"{field}.kind must be pull_request or public_safe_patch")
        source_ref = _git_ref(raw.get("ref"), f"{field}.ref")
        if source_ref in source_refs:
            raise ValueError(f"duplicate integration source ref: {source_ref}")
        source_refs.add(source_ref)
        changed_seams = _string_list(raw.get("changed_seams"), f"{field}.changed_seams")
        if not changed_seams:
            raise ValueError(f"{field}.changed_seams must not be empty")
        unknown = sorted(set(changed_seams) - ALLOWED_CHANGE_SEAMS)
        if unknown:
            raise ValueError(f"{field} has unsupported changed seams: {unknown}")
        covered_seams.update(changed_seams)
        sources.append(
            {
                "id": source_id,
                "kind": kind,
                "ref": source_ref,
                "head_sha": _git_sha(raw.get("head_sha"), f"{field}.head_sha"),
                "changed_seams": changed_seams,
            }
        )

    missing_seams = sorted(set(required_seams) - covered_seams)
    if missing_seams:
        raise ValueError(
            f"integration candidate does not cover required seams: {missing_seams}"
        )

    def receipt(raw: Any, field: str) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise TypeError(f"{field} must be an object")
        _reject_unexpected_keys(
            raw, {"base_sha", "integration_sha", "source_heads"}, field
        )
        raw_heads = raw.get("source_heads")
        if not isinstance(raw_heads, Mapping):
            raise TypeError(f"{field}.source_heads must be an object")
        if set(raw_heads) != source_ids:
            raise ValueError(f"{field}.source_heads must match integration source ids")
        return {
            "base_sha": _git_sha(raw.get("base_sha"), f"{field}.base_sha"),
            "integration_sha": _git_sha(
                raw.get("integration_sha"), f"{field}.integration_sha"
            ),
            "source_heads": {
                source_id: _git_sha(
                    raw_heads[source_id], f"{field}.source_heads.{source_id}"
                )
                for source_id in sorted(source_ids)
            },
        }

    observed = receipt(candidate.get("observed"), "integration.observed")
    last_sync = receipt(candidate.get("last_sync"), "integration.last_sync")
    for source in sources:
        if observed["source_heads"][source["id"]] != source["head_sha"]:
            raise ValueError(
                f"observed source head does not match declared head for {source['id']}"
            )

    drift_reasons: list[dict[str, str]] = []
    if observed["base_sha"] != last_sync["base_sha"]:
        drift_reasons.append(
            {
                "kind": "base_moved",
                "ref": base_ref,
                "last_sync_sha": last_sync["base_sha"],
                "observed_sha": observed["base_sha"],
            }
        )
    for source in sources:
        source_id = source["id"]
        if observed["source_heads"][source_id] != last_sync["source_heads"][source_id]:
            drift_reasons.append(
                {
                    "kind": "source_moved",
                    "source_id": source_id,
                    "last_sync_sha": last_sync["source_heads"][source_id],
                    "observed_sha": observed["source_heads"][source_id],
                }
            )
    if observed["integration_sha"] != last_sync["integration_sha"]:
        drift_reasons.append(
            {
                "kind": "integration_head_moved",
                "ref": integration_branch,
                "last_sync_sha": last_sync["integration_sha"],
                "observed_sha": observed["integration_sha"],
            }
        )

    sync_required = bool(drift_reasons)
    return {
        "schema_version": INTEGRATION_CANDIDATE_SCHEMA_VERSION,
        "status": "sync_required" if sync_required else "in_sync",
        "sync_required": sync_required,
        "drift_reasons": drift_reasons,
        "required_seams": required_seams,
        "covered_seams": sorted(covered_seams),
        "source_order": sources,
        "core_integration_plan": {
            "base_ref": base_ref,
            "integration_branch": integration_branch,
            "source_refs": [source["ref"] for source in sources],
        },
        "reconcile_steps": [
            "refresh_declared_remote_refs_read_only",
            "verify_every_ref_resolves_to_declared_head",
            "preview_core_integration_branch_sync",
            "execute_local_sync_with_explicit_write_authority",
            "run_changed_seam_and_build_validation",
            "push_candidate_only_after_validation",
        ],
        "deployment_contract": {
            "artifact": "content_addressed_binary_with_sha256",
            "sequence": [
                "retain_previous_binary_and_config_pointer",
                "run_isolated_smoke",
                "compare_configuration_by_field",
                "switch_operator_owned_pointer",
                "read_back_catalog_retry_and_runtime",
            ],
            "rollback_trigger": "any_failed_readback_or_unexplained_regression",
            "session_store_policy": "preserve_in_place_never_copy_or_delete",
        },
        "effect_boundary": "read_only_public_safe_plan",
    }
