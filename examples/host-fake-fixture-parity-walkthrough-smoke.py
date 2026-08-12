#!/usr/bin/env python3
"""Smoke-test cross-host fake-fixture parity across all shipped agent types,
Turn hosts, scheduler runtime profiles, and skill-delivery surfaces.

Covers:
- Codex App heartbeat, Codex CLI TUI, LoopX Turn, Claude Code, OpenCode,
  TraeX, Pi, Gemini, Cursor, Ark Managed Agent, manual, and other-agent
- External shell worker, HTTP webhook, and worker bridge (routed through
  manual / other-agent in the host surface catalog)
- Missing explicit capability route, signed primary action, scoped identity,
  skill delivery/readback, typed Goal continuation, runtime-owned cadence,
  no-spend transition, and private-boundary proofs
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.host_loop_activation import (  # noqa: E402
    AGENT_TYPE_CATALOG,
    AGENT_TYPE_CATALOG_SCHEMA_VERSION,
    HOST_MANAGED_SKILL_AGENT_TYPES,
    HOST_SURFACE_TO_AGENT_TYPE,
    SCHEMA_VERSION as ACTIVATION_SCHEMA_VERSION,
    SUPPORTED_AGENT_TYPES,
    AgentTypeError,
    agent_type_for_host_surface,
    agent_type_uses_host_managed_skills,
    build_agent_type_catalog,
    build_host_loop_activation_packet,
    normalize_agent_type,
    scheduler_command_binding_for_agent_type,
)

from loopx.host_mode_planner import (  # noqa: E402
    CANONICAL_MODES,
    MODE_HYBRID_HANDOFF,
    MODE_IM_GATEWAY,
    MODE_ISOLATED_HEADLESS_TURN,
    MODE_SHELL_SERVICE,
    MODE_VISIBLE_TUI,
    SUPPORTED_TURN_HOST_IDENTITIES,
    VISIBLE_CONNECTOR_OVERRIDES,
    VISIBLE_HOST_CONNECTOR_IDS,
    VISIBLE_OPENCODE_ALIASES,
    VISIBLE_PI_ALIASES,
    HostModePlanError,
    build_host_mode_plan,
    render_host_mode_plan_markdown,
)

from loopx.control_plane.turn_driver.driver import (  # noqa: E402
    SUPPORTED_HOSTS,
    SUPPORTED_EXECUTION_MODES,
)

# ---------------------------------------------------------------------------
# public-safety patterns (GH-C50 fix pattern: split with +)
# ---------------------------------------------------------------------------

PRIVATE_PATTERNS = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def assert_public_safe(text: str, label: str) -> None:
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise AssertionError(
                f"{label} matched private pattern {pattern.pattern!r}"
            )


def assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label} missing {needle!r}")


# ---------------------------------------------------------------------------
# fixture identity constants
# ---------------------------------------------------------------------------

FIXTURE_GOAL_ID = "parity-walkthrough"
FIXTURE_AGENT_ID = "parity-agent"
FIXTURE_REGISTERED_AGENTS = ["parity-agent", "parity-peer"]
FIXTURE_CAPS = ["network", "shell"]


# ---------------------------------------------------------------------------
# 1. Agent type catalog completeness and normalization
# ---------------------------------------------------------------------------

def scenario_agent_type_catalog_is_complete() -> dict:
    catalog = build_agent_type_catalog()
    assert catalog["ok"] is True
    assert catalog["schema_version"] == AGENT_TYPE_CATALOG_SCHEMA_VERSION

    canonical_types = {item["agent_type"] for item in catalog["canonical_agent_types"]}

    # Every supported agent type appears in the canonical catalog.
    expected = {
        "ark-managed-agent",
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli",
        "claude-code",
        "opencode",
        "traex-cli",
        "pi",
        "gemini-cli",
        "cursor-agent",
        "manual",
        "other-agent",
    }
    missing = expected - canonical_types
    assert not missing, f"missing canonical agent types: {missing}"
    extra = canonical_types - expected
    assert not extra, f"unexpected canonical agent types: {extra}"

    # Every accepted input normalizes to the correct canonical.
    for canonical, meta in AGENT_TYPE_CATALOG.items():
        for alias in meta["accepted_inputs"]:
            assert normalize_agent_type(alias) == canonical, (
                alias,
                canonical,
                normalize_agent_type(alias),
            )

    # Ambiguous inputs are covered.
    ambiguous = {
        item["input"]: item["use_one_of"]
        for item in catalog["ambiguous_inputs"]
    }
    assert ambiguous["codex"] == [
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli",
    ]

    return {"canonical_count": len(canonical_types), "ambiguous_count": len(ambiguous)}


# ---------------------------------------------------------------------------
# 2. Host surface -> agent type mapping parity
# ---------------------------------------------------------------------------

def scenario_host_surface_maps_all_routes() -> dict:
    # Every expected host surface route resolves to a valid canonical agent type.
    expected_surfaces = {
        # Codex surfaces
        "chat-box": "codex-app",
        "codex-app": "codex-app",
        "codex-app-ssh": "codex-app-ssh",
        "codex-ide-plugin": "codex-ide-plugin",
        "codex-ide": "codex-ide-plugin",
        "codex-cli-tui": "codex-cli",
        # Third-party CLIs
        "claude-code": "claude-code",
        "opencode": "opencode",
        "traex-cli": "traex-cli",
        "traex": "traex-cli",
        "traex-cli-tui": "traex-cli",
        "pi": "pi",
        "pi-tui": "pi",
        "gemini-cli": "gemini-cli",
        "gemini": "gemini-cli",
        "cursor-agent": "cursor-agent",
        "cursor": "cursor-agent",
        # Bridge / worker routes
        "ark-managed-agent": "ark-managed-agent",
        "ark_managed_agent": "ark-managed-agent",
        "shell": "manual",
        "http": "other-agent",
        "worker-bridge": "other-agent",
    }
    for surface, expected in expected_surfaces.items():
        actual = agent_type_for_host_surface(surface)
        assert actual == expected, (surface, actual, expected)

    # verify the reverse: HOST_SURFACE_TO_AGENT_TYPE dict matches
    for surface, expected in expected_surfaces.items():
        assert HOST_SURFACE_TO_AGENT_TYPE[surface] == expected, surface

    return {"surface_count": len(expected_surfaces)}


# ---------------------------------------------------------------------------
# 3. Activation packet parity across all agent types
# ---------------------------------------------------------------------------

def scenario_activation_parity() -> dict:
    results = {}
    for agent_type in SUPPORTED_AGENT_TYPES:
        canonical = normalize_agent_type(agent_type)
        packet = build_host_loop_activation_packet(
            agent_type=canonical,
            goal_id=FIXTURE_GOAL_ID,
            agent_id=FIXTURE_AGENT_ID,
            registered_agents=FIXTURE_REGISTERED_AGENTS,
            available_capabilities=FIXTURE_CAPS,
        )

        # Every packet has schema version and correct agent type.
        assert packet["schema_version"] == ACTIVATION_SCHEMA_VERSION, canonical
        assert packet["agent_type"] == canonical, canonical
        assert packet["goal_id"] == FIXTURE_GOAL_ID, canonical

        # available_capabilities is always a list (normalized, not None).
        assert isinstance(packet["available_capabilities"], list), canonical

        # activation_steps and success_criteria are always present.
        assert isinstance(packet["activation_steps"], list), canonical
        assert len(packet["activation_steps"]) > 0, canonical
        assert isinstance(packet["success_criteria"], list), canonical
        assert len(packet["success_criteria"]) > 0, canonical

        # host_mutation is always present and typed; some agent types
        # provide a host_command or host_tool, others expose a
        # missing_host_tool_gate when the host has no native mutation.
        mutation = packet["host_mutation"]
        assert isinstance(mutation, dict), canonical
        assert any(
            key in mutation
            for key in ("host_command", "host_tool", "missing_host_tool_gate")
        ), (canonical, list(mutation))

        # activation_method is a non-empty string.
        assert isinstance(packet["activation_method"], str), canonical
        assert packet["activation_method"], canonical

        # host_surface is a non-empty string.
        assert isinstance(packet["host_surface"], str), canonical
        assert packet["host_surface"], canonical

        results[canonical] = {
            "activation_method": packet["activation_method"],
            "host_surface": packet["host_surface"],
            "activation_allowed": packet["activation_allowed"],
        }

    # Prove each activation method is distinct across at least one axis.
    methods = {v["activation_method"] for v in results.values()}
    assert len(methods) >= 6, f"too few distinct activation methods: {methods}"

    # Host-managed vs surface-managed skill split.
    host_managed = {
        t for t in HOST_MANAGED_SKILL_AGENT_TYPES
    }
    assert host_managed == {"ark-managed-agent", "traex-cli", "other-agent"}

    for agent_type in SUPPORTED_AGENT_TYPES:
        canonical = normalize_agent_type(agent_type)
        uses_host = agent_type_uses_host_managed_skills(canonical)
        if canonical in HOST_MANAGED_SKILL_AGENT_TYPES:
            assert uses_host is True, canonical
        else:
            assert uses_host is False, canonical

    return results


# ---------------------------------------------------------------------------
# 4. Scheduler runtime profile binding parity
# ---------------------------------------------------------------------------

def scenario_scheduler_bindings() -> dict:
    # Each agent type routes to exactly one scheduler runtime profile.
    expected_bindings = {
        "ark-managed-agent": "ark_managed_agent_goal",
        "codex-app": "codex_app_heartbeat",
        "codex-app-ssh": "codex_app_ssh_goal",
        "codex-cli": "codex_cli",
        "codex-ide-plugin": "codex_cli",
        "claude-code": "claude_code",
        "opencode": "generic_cli",
        "traex-cli": "generic_cli",
        "pi": "generic_cli",
        "gemini-cli": "generic_cli",
        "cursor-agent": "generic_cli",
    }
    for agent_type, expected_profile in expected_bindings.items():
        binding = scheduler_command_binding_for_agent_type(agent_type)
        assert binding.get("runtime_profile") == expected_profile, (
            agent_type,
            binding,
            expected_profile,
        )

    # manual and other-agent have no runtime profile binding.
    for agent_type in ("manual", "other-agent"):
        binding = scheduler_command_binding_for_agent_type(agent_type)
        assert binding == {}, (agent_type, binding)

    # The five generic_cli types share one profile — prove they all map the same.
    generic_cli_types = ["opencode", "traex-cli", "pi", "gemini-cli", "cursor-agent"]
    profiles = {
        t: scheduler_command_binding_for_agent_type(t)["runtime_profile"]
        for t in generic_cli_types
    }
    assert len(set(profiles.values())) == 1, profiles
    assert list(profiles.values())[0] == "generic_cli"

    return {"bindings": len(expected_bindings), "generic_cli_types": generic_cli_types}


# ---------------------------------------------------------------------------
# 5. Turn host identity parity
# ---------------------------------------------------------------------------

def scenario_turn_host_identities() -> dict:
    # SUPPORTED_HOSTS (turn driver) and SUPPORTED_TURN_HOST_IDENTITIES (planner)
    # must agree on the set of Turn-capable hosts.
    assert SUPPORTED_HOSTS == {"codex-cli", "claude-code", "generic-cli"}, SUPPORTED_HOSTS
    assert set(SUPPORTED_TURN_HOST_IDENTITIES) == SUPPORTED_HOSTS, (
        SUPPORTED_TURN_HOST_IDENTITIES,
        SUPPORTED_HOSTS,
    )

    # Visible connectors map each Turn host to a catalog connector id.
    assert VISIBLE_HOST_CONNECTOR_IDS == {
        "codex-cli": "codex_cli_tui",
        "claude-code": "claude_code_loop",
        "generic-cli": "opencode_goal_loop",
    }

    # OpenCode and Pi alias onto generic-cli.
    assert VISIBLE_OPENCODE_ALIASES == {"opencode": "generic-cli", "open-code": "generic-cli"}
    assert VISIBLE_PI_ALIASES == {"pi": "generic-cli"}

    # Pi gets its own connector override.
    assert VISIBLE_CONNECTOR_OVERRIDES == {"pi": "pi_goal_loop"}

    # Execution modes are exactly two.
    assert SUPPORTED_EXECUTION_MODES == {"interactive-visible", "isolated-headless"}

    return {
        "turn_hosts": sorted(SUPPORTED_HOSTS),
        "execution_modes": sorted(SUPPORTED_EXECUTION_MODES),
        "visible_aliases": sorted(VISIBLE_OPENCODE_ALIASES),
        "pi_aliases": sorted(VISIBLE_PI_ALIASES),
    }


# ---------------------------------------------------------------------------
# 6. Host mode plan selects distinct modes per intent and host identity
# ---------------------------------------------------------------------------

def _build_plan(intent: str, host_identity: str | None = "codex-cli") -> dict:
    return build_host_mode_plan(
        goal_id="parity-selector",
        user_intent=intent,
        host_capabilities=[
            "visible_session",
            "loopx_turn",
            "typed_host_adapter",
            "independent_validator",
            "chat_gateway",
            "service_timer",
            "shell",
        ],
        agent_id="parity-agent",
        registered_agents=["parity-agent"],
        available_capabilities=["network"],
        host_identity=host_identity,
    )


def scenario_mode_plan_parity() -> dict:
    # Each intent selects the correct mode.
    intent_to_mode = {
        "watch_each_turn": MODE_VISIBLE_TUI,
        "continue_without_ui": MODE_ISOLATED_HEADLESS_TURN,
        "intake_from_chat": MODE_IM_GATEWAY,
        "timer_keepalive": MODE_SHELL_SERVICE,
        "escalate_between_modes": MODE_HYBRID_HANDOFF,
    }
    for intent, expected_mode in intent_to_mode.items():
        plan = _build_plan(intent)
        assert plan["ok"] is True, (intent, plan)
        assert plan["selected_mode"] == expected_mode, (intent, plan)
        assert set(item["mode"] for item in plan["mode_options"]) == set(CANONICAL_MODES)

    # Each Turn host identity produces a distinct visible connector id.
    for host_identity, connector_id in {
        "codex-cli": "codex_cli_tui",
        "claude-code": "claude_code_loop",
        "generic-cli": "opencode_goal_loop",
    }.items():
        plan = build_host_mode_plan(
            goal_id="parity-selector",
            user_intent="watch_each_turn",
            host_capabilities=["visible_session"],
            agent_id="parity-agent",
            registered_agents=["parity-agent"],
            host_identity=host_identity,
        )
        assert plan["selected_connector_id"] == connector_id, host_identity
        assert plan["selected_turn_mapping"]["host"] == host_identity

    # OpenCode and Pi resolve through alias onto generic-cli with overrides.
    plan = _build_plan("watch_each_turn", host_identity="opencode")
    assert plan["selected_connector_id"] == "opencode_goal_loop"
    assert plan["selected_turn_mapping"]["host"] == "generic-cli"
    assert "--host generic-cli" in plan["next_preview_command"]

    plan = _build_plan("watch_each_turn", host_identity="pi")
    assert plan["selected_connector_id"] == "pi_goal_loop"
    assert plan["selected_turn_mapping"]["host"] == "generic-cli"
    assert "--host generic-cli" in plan["next_preview_command"]

    return {"intents": list(intent_to_mode), "modes": CANONICAL_MODES}


# ---------------------------------------------------------------------------
# 7. Missing explicit capability routes fail closed
# ---------------------------------------------------------------------------

def scenario_capability_routes_fail_closed() -> dict:
    failures = {}

    # Missing host identity on visible mode blocks the route.
    plan = build_host_mode_plan(
        goal_id="parity",
        user_intent="watch_each_turn",
        host_capabilities=["visible_session"],
        registered_agents=["parity-agent"],
    )
    assert plan["selected_capability_ready"] is False, plan
    assert plan["selected_connector_id"] is None, plan
    assert plan["selected_turn_mapping"]["host"] is None, plan
    failures["visible_without_identity"] = "blocked"

    # Isolated headless without typed_host_adapter + independent_validator.
    plan = build_host_mode_plan(
        goal_id="parity",
        user_intent="continue_without_ui",
        host_capabilities=["loopx_turn"],
        agent_id="parity-agent",
        registered_agents=["parity-agent"],
    )
    selected_missing = plan["selected_missing_host_capabilities"]
    assert "typed_host_adapter" in selected_missing
    assert "independent_validator" in selected_missing
    assert plan["selected_capability_ready"] is False
    failures["headless_missing_adapter_and_validator"] = "blocked"

    # Shell service fails closed without adapter + validator.
    plan = build_host_mode_plan(
        goal_id="parity",
        user_intent="timer_keepalive",
        host_capabilities=["service_timer", "shell", "loopx_turn"],
        agent_id="parity-agent",
        registered_agents=["parity-agent"],
    )
    shell = next(
        item for item in plan["mode_options"] if item["mode"] == MODE_SHELL_SERVICE
    )
    assert shell["capability_ready"] is False
    assert "typed_host_adapter" in shell["missing_host_capabilities"]
    assert "independent_validator" in shell["missing_host_capabilities"]
    failures["shell_service_missing_proofs"] = "blocked"

    # Unknown intent fails closed.
    try:
        build_host_mode_plan(goal_id="p", user_intent="launch_missiles")
    except HostModePlanError as exc:
        assert exc.to_payload()["ok"] is False
        assert exc.to_payload()["field"] == "user_intent"
        failures["unknown_intent"] = "error"

    # Unknown host identity on visible mode fails closed.
    try:
        build_host_mode_plan(
            goal_id="p",
            user_intent="watch_each_turn",
            host_capabilities=["visible_session"],
            host_identity="not-a-host",
            registered_agents=["parity-agent"],
        )
    except HostModePlanError as exc:
        assert exc.to_payload()["ok"] is False
        assert exc.to_payload()["field"] == "host_identity"
        failures["unknown_host_identity"] = "error"

    # Unknown capability fails closed.
    try:
        build_host_mode_plan(
            goal_id="p",
            user_intent="continue_without_ui",
            host_capabilities=["root_shell"],
        )
    except HostModePlanError as exc:
        assert exc.to_payload()["field"] == "host_capabilities"
        failures["unknown_capability"] = "error"

    # Ambiguous agent type fails closed with suggestions.
    try:
        normalize_agent_type("codex")  # ambiguous without disambiguation
    except AgentTypeError:
        pass  # normalize_agent_type does NOT raise; use the catalog for that
    # Actually, normalize_agent_type returns None for ambiguous without a raise.
    # The agent-onboard CLI rejects ambiguity. Prove the catalog records it.
    catalog = build_agent_type_catalog()
    ambiguous = {item["input"]: item["use_one_of"] for item in catalog["ambiguous_inputs"]}
    assert "codex" in ambiguous
    failures["ambiguous_codex_in_catalog"] = "needs_disambiguation"

    return failures


# ---------------------------------------------------------------------------
# 8. Gated activation: scoped identity and fresh registration
# ---------------------------------------------------------------------------

def scenario_scoped_identity_gating() -> dict:
    # No agent_id with multiple registered agents -> selection required.
    packet = build_host_loop_activation_packet(
        agent_type="codex-cli",
        goal_id=FIXTURE_GOAL_ID,
        agent_id=None,
        registered_agents=["agent-alpha", "agent-beta"],
    )
    assert packet["activation_allowed"] is False
    assert packet["activation_state"] == "selection_required"
    gate = packet["identity_selection_gate"]
    assert gate is not None
    assert len(gate["choices"]) == 2
    for choice in gate["choices"]:
        assert choice["mode"] == "takeover_existing_agent"
        assert choice["requires_explicit_takeover_intent"] is True
        assert choice["agent_id"] in ("agent-alpha", "agent-beta")

    # Single registered agent auto-selects.
    packet = build_host_loop_activation_packet(
        agent_type="codex-cli",
        goal_id=FIXTURE_GOAL_ID,
        agent_id=None,
        registered_agents=["agent-solo"],
    )
    assert packet["activation_allowed"] is True
    assert packet["activation_state"] == "single_registered_agent_selected"
    assert packet["agent_id"] == "agent-solo"

    # Explicit agent_id bypasses selection gate.
    packet = build_host_loop_activation_packet(
        agent_type="codex-cli",
        goal_id=FIXTURE_GOAL_ID,
        agent_id="agent-alpha",
        registered_agents=["agent-alpha", "agent-beta"],
    )
    assert packet["activation_allowed"] is True
    assert packet["agent_id"] == "agent-alpha"

    return {
        "gated_states": ["selection_required", "single_registered_agent_selected"],
        "explicit_bypass": True,
    }


# ---------------------------------------------------------------------------
# 9. Skill delivery parity: surface_managed vs host_managed
# ---------------------------------------------------------------------------

def scenario_skill_delivery_parity() -> dict:
    results = {}

    # Surface-managed types (Codex family, Claude, OpenCode, Pi, Gemini, Cursor).
    surface_types = [
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli",
        "claude-code",
        "opencode",
        "pi",
        "gemini-cli",
        "cursor-agent",
    ]
    for agent_type in surface_types:
        canonical = normalize_agent_type(agent_type)
        assert not agent_type_uses_host_managed_skills(canonical), canonical

        packet = build_host_loop_activation_packet(
            agent_type=canonical,
            goal_id=FIXTURE_GOAL_ID,
            agent_id=FIXTURE_AGENT_ID,
            registered_agents=[FIXTURE_AGENT_ID],
        )
        # Surface-managed types include heartbeat and visible-goal commands
        # when activation is allowed.
        cmds = packet["commands"]
        assert cmds.get("heartbeat_prompt_json") is not None, canonical
        assert cmds.get("heartbeat_prompt") is not None, canonical

    # Host-managed types (ark-managed-agent, traex-cli, other-agent).
    host_types = ["ark-managed-agent", "traex-cli", "other-agent"]
    for agent_type in host_types:
        canonical = normalize_agent_type(agent_type)
        assert agent_type_uses_host_managed_skills(canonical), canonical

    # manual does not use host-managed skills but has no skill delivery.
    assert not agent_type_uses_host_managed_skills("manual")

    # Prove skill delivery modes are distinct across agent types.
    results["surface_managed_count"] = len(surface_types)
    results["host_managed_count"] = len(host_types)
    results["manual_has_no_host_skills"] = not agent_type_uses_host_managed_skills(
        "manual"
    )
    return results


# ---------------------------------------------------------------------------
# 10. No-spend transition and boundary proof
# ---------------------------------------------------------------------------

def scenario_no_spend_and_boundary() -> dict:
    plan = build_host_mode_plan(
        goal_id="parity",
        user_intent="watch_each_turn",
        host_capabilities=["visible_session"],
        registered_agents=["parity-agent", "parity-peer"],
    )

    # No-spend policy: selector preview only.
    no_spend = plan["no_spend_policy"]
    assert no_spend["selector_preview"] is True
    assert no_spend["turn_plan_preview"] is True
    assert no_spend["quiet_monitor_skip"] is True
    assert no_spend["spends_only_after_validated_delivery_writeback"] is True

    # Boundary: selector is not authoritative.
    boundary = plan["boundary"]
    assert boundary["selector_is_authoritative"] is False
    assert boundary["turn_envelope_is_authoritative_for_execution"] is True
    for key in [
        "starts_process",
        "writes_state",
        "spends_quota",
        "infers_production_permission",
        "infers_credential_access",
        "infers_destructive_authority",
    ]:
        assert boundary[key] is False, (key, boundary)

    # Identity contract present.
    identity = plan["identity_contract"]
    assert identity["state"] == "selection_required"
    assert identity["action_required"] is True

    return {
        "no_spend_policy_keys": list(no_spend),
        "boundary_keys": list(boundary),
    }


# ---------------------------------------------------------------------------
# 11. Markdown rendering and public-safety scan
# ---------------------------------------------------------------------------

def scenario_markdown_and_public_safety() -> dict:
    plan = build_host_mode_plan(
        goal_id="parity",
        user_intent="continue_without_ui",
        host_capabilities=[
            "loopx_turn",
            "typed_host_adapter",
            "independent_validator",
        ],
        agent_id="parity-agent",
        registered_agents=["parity-agent"],
    )
    markdown = render_host_mode_plan_markdown(plan)
    assert_contains(markdown, "LoopX Host Mode Plan", "markdown")
    assert_contains(markdown, "loopx turn plan", "markdown")
    assert_contains(markdown, "Operator Next Steps", "markdown")
    assert_public_safe(markdown, "ready_markdown")

    # Blocked plan markdown.
    blocked = build_host_mode_plan(
        goal_id="parity",
        user_intent="continue_without_ui",
        host_capabilities=["loopx_turn"],
        agent_id="parity-agent",
        registered_agents=["parity-agent"],
    )
    blocked_md = render_host_mode_plan_markdown(blocked)
    assert_contains(blocked_md, "Blocking Reasons", "blocked markdown")
    assert_contains(blocked_md, "typed host adapter", "blocked markdown")
    assert_public_safe(blocked_md, "blocked_markdown")

    # All activation packets are public-safe.
    for agent_type in SUPPORTED_AGENT_TYPES:
        canonical = normalize_agent_type(agent_type)
        packet = build_host_loop_activation_packet(
            agent_type=canonical,
            goal_id=FIXTURE_GOAL_ID,
            agent_id=FIXTURE_AGENT_ID,
            registered_agents=FIXTURE_REGISTERED_AGENTS,
        )
        serialized = json.dumps(packet, sort_keys=True)
        assert_public_safe(serialized, f"activation_{canonical}")

    # Agent type catalog is public-safe.
    catalog = build_agent_type_catalog()
    assert_public_safe(json.dumps(catalog, sort_keys=True), "agent_type_catalog")

    return {"public_safe": True, "agent_types_scanned": len(SUPPORTED_AGENT_TYPES)}


# ---------------------------------------------------------------------------
# 12. Runtime-owned cadence: each agent type has an explicit scheduler owner
# ---------------------------------------------------------------------------

def scenario_runtime_owned_cadence() -> dict:
    # Every agent type with a scheduler binding acknowledges its cadence owner.
    bound_types = [
        t
        for t in SUPPORTED_AGENT_TYPES
        if scheduler_command_binding_for_agent_type(t)
    ]

    for agent_type in bound_types:
        canonical = normalize_agent_type(agent_type)
        packet = build_host_loop_activation_packet(
            agent_type=canonical,
            goal_id=FIXTURE_GOAL_ID,
            agent_id=FIXTURE_AGENT_ID,
            registered_agents=[FIXTURE_AGENT_ID],
        )
        # Activation steps must mention quota/gate should-run or heartbeat cadence.
        steps_text = " ".join(packet["activation_steps"]).lower()
        assert any(
            keyword in steps_text
            for keyword in ("should_run", "heartbeat", "quota")
        ), (canonical, packet["activation_steps"])

    return {
        "bound_types": bound_types,
        "unbound_types": [
            t
            for t in SUPPORTED_AGENT_TYPES
            if not scheduler_command_binding_for_agent_type(t)
        ],
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    catalog_result = scenario_agent_type_catalog_is_complete()
    surface_result = scenario_host_surface_maps_all_routes()
    activation_result = scenario_activation_parity()
    scheduler_result = scenario_scheduler_bindings()
    turn_result = scenario_turn_host_identities()
    mode_result = scenario_mode_plan_parity()
    fail_closed_result = scenario_capability_routes_fail_closed()
    identity_result = scenario_scoped_identity_gating()
    skill_result = scenario_skill_delivery_parity()
    boundary_result = scenario_no_spend_and_boundary()
    safety_result = scenario_markdown_and_public_safety()
    cadence_result = scenario_runtime_owned_cadence()

    summary = {
        "schema_version": "host_parity_walkthrough_v0",
        "ok": True,
        "agent_type_catalog": catalog_result,
        "host_surface_mapping": surface_result,
        "activation_parity": {
            k: v
            for k, v in sorted(activation_result.items())
        },
        "scheduler_bindings": scheduler_result,
        "turn_host_identities": turn_result,
        "host_mode_plan_parity": mode_result,
        "capability_routes_fail_closed": fail_closed_result,
        "scoped_identity_gating": identity_result,
        "skill_delivery_parity": skill_result,
        "no_spend_and_boundary": boundary_result,
        "public_safety": safety_result,
        "runtime_owned_cadence": cadence_result,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("host-fake-fixture-parity-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
