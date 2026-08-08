from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ...bootstrap_command_pack import build_start_goal_guided_packet
from ..quota.cli_projection import compact_quota_should_run_cli_payload
from ..quota.turn_envelope import quota_action_signature_document
from ..work_items.interaction_contract import build_interaction_contract
from .control_plane_composition_scenarios import (
    build_control_plane_composition_scenario_sources,
)
from .model_behavior_qualification import (
    MODEL_BEHAVIOR_HARD_INVARIANT_FIELDS,
    ModelBehaviorActor,
    _actor_failure_code,
    build_model_behavior_actor_request,
    model_behavior_semantic_contract_from_packet,
    run_model_behavior_qualification_arm,
)
from .onboarding_model_behavior_qualification import (
    OnboardingActualBehaviorValidationError,
    OnboardingModelBehaviorActor,
    _behavior_contract_violations,
    _semantic_contract,
    _validate_actual_default_projection,
    build_onboarding_model_behavior_actor_request,
    build_onboarding_postcondition_observation,
    run_onboarding_model_behavior_phase,
)

ACTUAL_DEFAULT_MODEL_BEHAVIOR_PORTFOLIO_SCHEMA_VERSION = (
    "actual_default_model_behavior_portfolio_v0"
)
ACTUAL_DEFAULT_MODEL_BEHAVIOR_CATALOG_SCHEMA_VERSION = (
    "actual_default_model_behavior_scenario_catalog_v0"
)
ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS = 2
ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID = "portfolio-goal"
ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID = "codex-portfolio"
ACTUAL_DEFAULT_MODEL_BEHAVIOR_HOT_PATH_JSON_BUDGET = 40_000
ACTUAL_DEFAULT_MODEL_BEHAVIOR_CONTRAST_SCHEMA_VERSION = (
    "actual_default_model_behavior_contrast_v0"
)


@dataclass(frozen=True)
class _ScenarioSpec:
    scenario_id: str
    actor_kind: str
    phase: str | None
    expected_route: str
    scenario_family: str = "core_contract"
    composition_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ContrastSpec:
    contrast_id: str
    contrast_kind: str
    left_scenario_id: str
    right_scenario_id: str
    must_match_fields: tuple[str, ...]
    must_differ_fields: tuple[str, ...] = ()


_SCENARIOS = (
    _ScenarioSpec(
        "onboarding_connect_default",
        "onboarding",
        "entry",
        "connect_if_needed",
    ),
    _ScenarioSpec(
        "onboarding_agent_identity_gate",
        "onboarding",
        "entry",
        "select_agent_identity",
    ),
    _ScenarioSpec(
        "onboarding_goal_selection_gate",
        "onboarding",
        "entry",
        "select_goal",
    ),
    _ScenarioSpec(
        "turn_selected_todo",
        "turn",
        None,
        "execute",
    ),
    _ScenarioSpec(
        "turn_peer_agent_identity",
        "turn",
        None,
        "execute",
    ),
    _ScenarioSpec(
        "turn_same_agent_continuation",
        "turn",
        None,
        "execute",
    ),
    _ScenarioSpec(
        "turn_human_gate",
        "turn",
        None,
        "ask_user",
    ),
    _ScenarioSpec(
        "turn_required_vision_replan",
        "turn",
        None,
        "execute",
        "control_plane_composition",
        ("vision", "monitor", "peer_ownership", "autonomous_replan"),
    ),
    _ScenarioSpec(
        "turn_scoped_gate_successor_replan",
        "turn",
        None,
        "execute",
        "control_plane_composition",
        ("user_gate", "deferred_successor", "non_blocking_notice", "scheduler"),
    ),
    _ScenarioSpec(
        "turn_capability_monitor_repair",
        "turn",
        None,
        "execute",
        "control_plane_composition",
        ("capability_gate", "monitor_schedule", "bridge_repair", "selected_action"),
    ),
    _ScenarioSpec(
        "turn_quota_hot_path_compaction_regression",
        "turn",
        None,
        "execute",
        "quota_cli_compaction_regression",
        (
            "json_budget",
            "source_semantics",
            "model_route",
        ),
    ),
    _ScenarioSpec(
        "turn_quota_hot_path_selected_todo_invariance",
        "turn",
        None,
        "execute",
        "quota_cli_compaction_contrast",
        ("selected_todo", "omitted_diagnostics", "invariance"),
    ),
    _ScenarioSpec(
        "turn_quota_hot_path_human_gate_invariance",
        "turn",
        None,
        "ask_user",
        "quota_cli_compaction_contrast",
        ("blocking_user_gate", "omitted_diagnostics", "invariance"),
    ),
    _ScenarioSpec(
        "onboarding_healthy_continue",
        "onboarding",
        "postcondition",
        "continue_validation",
    ),
    _ScenarioSpec(
        "onboarding_projection_repair",
        "onboarding",
        "postcondition",
        "repair_projection",
    ),
)
ACTUAL_DEFAULT_MODEL_BEHAVIOR_SCENARIO_COUNT = len(_SCENARIOS)

_HARD_INVARIANT_FIELDS = tuple(MODEL_BEHAVIOR_HARD_INVARIANT_FIELDS)
_CONTRASTS = (
    _ContrastSpec(
        "selected_todo_survives_omitted_diagnostics",
        "invariance",
        "turn_selected_todo",
        "turn_quota_hot_path_selected_todo_invariance",
        _HARD_INVARIANT_FIELDS,
    ),
    _ContrastSpec(
        "blocking_gate_survives_omitted_diagnostics",
        "invariance",
        "turn_human_gate",
        "turn_quota_hot_path_human_gate_invariance",
        _HARD_INVARIANT_FIELDS,
    ),
    _ContrastSpec(
        "blocking_gate_vs_non_blocking_notice",
        "sensitivity",
        "turn_human_gate",
        "turn_scoped_gate_successor_replan",
        (
            "user_action_required",
            "quiet_noop_allowed",
            "external_write_requested",
        ),
        (
            "decision",
            "selected_todo_id",
            "must_attempt_work",
            "delivery_allowed",
        ),
    ),
    _ContrastSpec(
        "selected_work_vs_required_vision_replan",
        "sensitivity",
        "turn_selected_todo",
        "turn_required_vision_replan",
        (
            "decision",
            "user_action_required",
            "must_attempt_work",
            "delivery_allowed",
            "quiet_noop_allowed",
            "external_write_requested",
        ),
        ("selected_todo_id",),
    ),
)
ACTUAL_DEFAULT_MODEL_BEHAVIOR_CONTRAST_COUNT = len(_CONTRASTS)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    )


def _digest(value: Any) -> str:
    return "sha256:" + sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def actual_default_model_behavior_scenario_catalog() -> dict[str, Any]:
    return {
        "schema_version": ACTUAL_DEFAULT_MODEL_BEHAVIOR_CATALOG_SCHEMA_VERSION,
        "topology": "actual_default_one_arm",
        "scenarios": [
            {
                "scenario_id": spec.scenario_id,
                "actor_kind": spec.actor_kind,
                "phase": spec.phase,
                "expected_route": spec.expected_route,
                "scenario_family": spec.scenario_family,
                "composition_dimensions": list(spec.composition_dimensions),
                "packet_view": (
                    "quota_should_run_default"
                    if spec.actor_kind == "turn"
                    else "guided_onboarding_default"
                ),
                "repeat_policy": {
                    "attempts": ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS,
                    "pass_condition": "all_attempts_source_aligned",
                    "automatic_retry_on_actor_error": False,
                },
            }
            for spec in _SCENARIOS
        ],
        "contrasts": [
            {
                "contrast_id": spec.contrast_id,
                "contrast_kind": spec.contrast_kind,
                "left_scenario_id": spec.left_scenario_id,
                "right_scenario_id": spec.right_scenario_id,
                "must_match_fields": list(spec.must_match_fields),
                "must_differ_fields": list(spec.must_differ_fields),
            }
            for spec in _CONTRASTS
        ],
    }


def _write_scenario_project(root: Path) -> tuple[Path, Path]:
    project = root / "project"
    state_file = (
        project
        / ".codex"
        / "goals"
        / ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID
        / "ACTIVE_GOAL_STATE.md"
    )
    state_file.parent.mkdir(parents=True)
    state_file.write_text("# Active Goal State\n", encoding="utf-8")
    registry_path = project / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state_file.relative_to(project)),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [
                                ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID
                            ],
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return project, registry_path


def _guided_scenario_packet(
    project: Path,
    *,
    goal_id: str | None,
    agent_id: str | None,
) -> dict[str, Any]:
    return build_start_goal_guided_packet(
        project=project,
        goal_id=goal_id,
        agent_id=agent_id,
        cli_bin="loopx",
        host_surface="codex-app",
        goal_text="Establish one public-safe quality contract.",
        available_capabilities=["network"],
        include_command_pack_detail=False,
    )


def _entry_scenario_packets(root: Path) -> dict[str, dict[str, Any]]:
    project, registry_path = _write_scenario_project(root)
    connect = _guided_scenario_packet(
        project,
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    )

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["goals"][0]["coordination"]["registered_agents"].append(
        "codex-portfolio-reviewer"
    )
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    identity = _guided_scenario_packet(
        project,
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        agent_id=None,
    )

    second_goal = "portfolio-second-goal"
    second_state = project / ".codex" / "goals" / second_goal / "ACTIVE_GOAL_STATE.md"
    second_state.parent.mkdir(parents=True)
    second_state.write_text("# Second Active Goal State\n", encoding="utf-8")
    registry["goals"].append(
        {
            "id": second_goal,
            "status": "active",
            "repo": str(project),
            "state_file": str(second_state.relative_to(project)),
            "coordination": {
                "agent_model": "peer_v1",
                "registered_agents": ["codex-portfolio-second"],
            },
        }
    )
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    goal_selection = _guided_scenario_packet(project, goal_id=None, agent_id=None)
    return {
        "onboarding_connect_default": connect,
        "onboarding_agent_identity_gate": identity,
        "onboarding_goal_selection_gate": goal_selection,
    }


def _turn_scenario_source(
    *,
    human_gate: bool,
    agent_id: str = ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    continuation_policy: str | None = None,
) -> dict[str, Any]:
    selected_todo = None
    if not human_gate:
        selected_todo = {
            "todo_id": "todo_portfolio001",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": agent_id,
            "text": "Implement one bounded public-safe slice.",
        }
        if continuation_policy:
            selected_todo["continuation_policy"] = continuation_policy
    payload: dict[str, Any] = {
        "ok": True,
        "mode": "should-run",
        "goal_id": ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        "decision": "skip" if human_gate else "run",
        "should_run": not human_gate,
        "effective_action": "operator_gate" if human_gate else "normal_run",
        "state": "operator_gate" if human_gate else "eligible",
        "requires_user_action": human_gate,
        "gate_prompt": ("Approve the bounded public release." if human_gate else None),
        "recommended_action": (
            "Approve the bounded public release."
            if human_gate
            else "Implement one bounded public-safe slice."
        ),
        "selected_todo": selected_todo,
        "agent_identity": {"agent_id": agent_id},
        "execution_obligation": {
            "must_attempt_work": not human_gate,
            "delivery_allowed": not human_gate,
        },
        "normal_delivery_allowed": not human_gate,
        "heartbeat_recommendation": {
            "notify": "NOTIFY" if human_gate else "DONT_NOTIFY"
        },
        "goal_boundary": {
            "write_scope": ["loopx/**", "tests/**"],
            "guards": ["stop before external writes"],
        },
    }
    payload["interaction_contract"] = build_interaction_contract(
        payload,
        available_capabilities=["network"],
    )
    payload["action_required"] = human_gate
    payload["open_count"] = 1 if human_gate else 0
    return payload


def build_quota_hot_path_compaction_regression_source() -> dict[str, Any]:
    """Build a coherent over-budget turn whose cold diagnostics are removable."""

    payload = _turn_scenario_source(human_gate=False)
    selected_todo = dict(payload["selected_todo"])
    selected_todo.update(
        {
            "todo_id": "todo_c0ffee123456",
            "text": "Implement the bounded hot-path qualification slice.",
        }
    )
    payload["selected_todo"] = selected_todo
    payload["recommended_action"] = selected_todo["text"]
    payload["interaction_contract"] = build_interaction_contract(
        payload,
        available_capabilities=["network", "shell", "filesystem_write"],
    )

    repeated_detail = "Bounded public-safe candidate diagnostic. " * 28

    def candidate(kind: str, index: int) -> dict[str, Any]:
        return {
            "todo_id": f"todo_{index:012x}",
            "status": "open",
            "priority": "P1",
            "task_class": "advancement_task",
            "action_kind": f"regression_{kind}",
            "claimed_by": ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
            "text": f"{kind} candidate {index}. {repeated_detail}",
        }

    runnable_candidates = [candidate("runnable", index) for index in range(1, 25)]
    blocked_candidates = [candidate("blocked", index) for index in range(25, 41)]
    resolution_bindings = [candidate("binding", index) for index in range(41, 57)]
    payload["capability_gate"] = {
        "schema_version": "capability_gate_v0",
        "required": ["shell", "filesystem_write"],
        "available": ["network", "shell", "filesystem_write"],
        "missing": [],
        "action": "run",
        "decision_owner": "agent",
        "candidate_order_policy": "claim_then_profile_then_priority",
        "runnable_count": len(runnable_candidates),
        "runnable_candidates": runnable_candidates,
        "blocked_candidates": blocked_candidates,
        "resolution_bindings": resolution_bindings,
    }

    lane_title = "Implement the bounded hot-path qualification slice."
    payload["agent_lane_next_action"] = {
        **selected_todo,
        "title": lane_title,
        "text": f"[P1] {lane_title}",
    }
    payload["active_state_next_action"] = (
        "Preserve the durable quality route while the peer lane remains independent."
    )
    payload["latest_run_recommended_action"] = selected_todo["text"]
    payload["next_action_projection_warning"] = {
        "schema_version": "next_action_projection_warning_v0",
        "kind": "next_action_projection_mismatch",
        "severity": "info",
        "requires_state_writeback": False,
        "active_state_next_action": payload["active_state_next_action"],
        "latest_run_recommended_action": payload["latest_run_recommended_action"],
        "agent_lane_next_action": payload["agent_lane_next_action"]["text"],
        "reason": "The agent lane is intentionally narrower than the durable route.",
        "recommended_action": selected_todo["text"],
    }
    peer_actions = [candidate("peer", index) for index in range(57, 81)]
    payload["goal_route_hint"] = {
        "schema_version": "goal_route_hint_v0",
        "route_decision": "run_current_agent_lane",
        "counts": {"other_agent_claimed_advancement_count": len(peer_actions)},
        "other_agent_next_actions": peer_actions,
    }
    return payload


def _build_quota_hot_path_selected_todo_invariance_source() -> dict[str, Any]:
    payload = build_quota_hot_path_compaction_regression_source()
    selected_todo = dict(payload["selected_todo"])
    selected_todo.update(
        {
            "todo_id": "todo_portfolio001",
            "text": "Implement one bounded public-safe slice.",
            "continuation_hint": "Next run the restart canary.",
        }
    )
    payload["selected_todo"] = selected_todo
    payload["recommended_action"] = selected_todo["text"]
    payload["active_state_next_action"] = "Inspect an obsolete branch."
    payload["latest_run_recommended_action"] = "Continue the previous run."
    payload["agent_lane_next_action"] = {
        **selected_todo,
        "title": selected_todo["text"],
        "text": f"[P1] {selected_todo['text']}",
    }
    warning = dict(payload["next_action_projection_warning"])
    warning["active_state_next_action"] = payload["active_state_next_action"]
    warning["latest_run_recommended_action"] = payload["latest_run_recommended_action"]
    warning["agent_lane_next_action"] = payload["agent_lane_next_action"]["text"]
    warning["recommended_action"] = selected_todo["text"]
    payload["next_action_projection_warning"] = warning
    payload["goal_route_hint"] = {
        **payload["goal_route_hint"],
        "selected_action_differs_from_durable": True,
        "current_agent_next_action": {"todo_id": selected_todo["todo_id"]},
    }
    payload["interaction_contract"] = build_interaction_contract(
        payload,
        available_capabilities=["network", "shell", "filesystem_write"],
    )
    return payload


def _build_quota_hot_path_human_gate_invariance_source() -> dict[str, Any]:
    payload = _turn_scenario_source(human_gate=True)
    noisy_source = build_quota_hot_path_compaction_regression_source()
    capability_gate = deepcopy(noisy_source["capability_gate"])
    capability_gate.update(
        {
            "required": [],
            "available": ["network"],
            "missing": [],
            "action": "operator_gate",
            "decision_owner": "user",
        }
    )
    payload["capability_gate"] = capability_gate
    goal_route_hint = deepcopy(noisy_source["goal_route_hint"])
    goal_route_hint["route_decision"] = "wait_for_blocking_user_gate"
    payload["goal_route_hint"] = goal_route_hint
    return payload


def _build_actual_default_model_behavior_scenario_sources(
    root: Path,
) -> dict[str, dict[str, Any]]:
    """Build authoritative pre-projection sources for behavior qualification."""

    packets = _entry_scenario_packets(root)
    packets.update(
        {
            "turn_selected_todo": _turn_scenario_source(human_gate=False),
            "turn_peer_agent_identity": _turn_scenario_source(
                human_gate=False,
                agent_id="codex-portfolio-reviewer",
            ),
            "turn_same_agent_continuation": _turn_scenario_source(
                human_gate=False,
                continuation_policy="same_agent_non_delivery",
            ),
            "turn_human_gate": _turn_scenario_source(human_gate=True),
            "turn_quota_hot_path_compaction_regression": (
                build_quota_hot_path_compaction_regression_source()
            ),
            "turn_quota_hot_path_selected_todo_invariance": (
                _build_quota_hot_path_selected_todo_invariance_source()
            ),
            "turn_quota_hot_path_human_gate_invariance": (
                _build_quota_hot_path_human_gate_invariance_source()
            ),
            "onboarding_healthy_continue": build_onboarding_postcondition_observation(
                check_warning_codes=[],
                executable_todo_count=1,
                selected_action_kind="quality_qualification",
                normal_delivery_allowed=True,
                user_action_required=False,
                next_action_actionable=True,
            ),
            "onboarding_projection_repair": build_onboarding_postcondition_observation(
                check_warning_codes=["state_projection_gap"],
                executable_todo_count=0,
                selected_action_kind=None,
                normal_delivery_allowed=False,
                user_action_required=False,
                next_action_actionable=True,
            ),
        }
    )
    packets.update(
        build_control_plane_composition_scenario_sources(
            goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
            agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
        )
    )
    return packets


def _compact_actual_default_model_behavior_scenario_sources(
    sources: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        scenario_id: (
            compact_quota_should_run_cli_payload(deepcopy(dict(packet)))
            if packet.get("mode") == "should-run"
            else deepcopy(dict(packet))
        )
        for scenario_id, packet in sources.items()
    }


def build_actual_default_model_behavior_scenario_inputs(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build paired source and actual-default actor packets from one fixture."""

    sources = _build_actual_default_model_behavior_scenario_sources(root)
    return sources, _compact_actual_default_model_behavior_scenario_sources(sources)


def build_actual_default_model_behavior_scenario_packets(
    root: Path,
) -> dict[str, dict[str, Any]]:
    """Build the default packets used by Codex App automation qualification."""

    _, packets = build_actual_default_model_behavior_scenario_inputs(root)
    return packets


def _turn_expected_contract(packet: Mapping[str, Any]) -> dict[str, Any]:
    if packet.get("mode") != "should-run":
        raise ValueError("turn scenarios require the default quota should-run packet")
    signature = quota_action_signature_document(packet)
    action = dict(signature.get("action") or {})
    user = dict(signature.get("user") or {})
    selected_todo = dict(action.get("selected_todo") or {})
    user_action_required = bool(user.get("action_required"))
    must_attempt = bool(action.get("must_attempt"))
    delivery_allowed = bool(action.get("delivery_allowed"))
    quiet_noop_allowed = bool(action.get("quiet_noop_allowed"))
    response_plan = signature.get("response_plan")
    blocking_user_gate = bool(
        isinstance(response_plan, Mapping)
        and response_plan.get("decision") == "ask_user"
    )
    if blocking_user_gate:
        route = "ask_user"
    elif must_attempt and delivery_allowed:
        route = "execute"
    elif must_attempt and not delivery_allowed and not quiet_noop_allowed:
        # Capability bridge repair, workspace repair, and similar agent-attempt
        # obligations are must-attempt work even though normal delivery is not
        # allowed: the agent must repair/materialize the missing bridge or write
        # a compact blocker instead of waiting or stopping.
        route = "execute"
    elif quiet_noop_allowed:
        route = "wait"
    else:
        route = "stop"
    contract = {
        "decision": route,
        "selected_todo_id": selected_todo.get("todo_id"),
        "user_action_required": user_action_required,
        "must_attempt_work": must_attempt,
        "delivery_allowed": delivery_allowed,
        "quiet_noop_allowed": quiet_noop_allowed,
        "external_write_requested": False,
    }
    if blocking_user_gate:
        contract["intended_action_kinds"] = ["notify", "wait"]
    return contract


def _validate_quota_hot_path_compaction_regression(
    source: Mapping[str, Any],
    packet: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    expected_selected_todo_id: str | None,
) -> None:
    if _pretty_json_size(source) <= ACTUAL_DEFAULT_MODEL_BEHAVIOR_HOT_PATH_JSON_BUDGET:
        raise ValueError("compaction-regression source must exceed the hot-path budget")
    if _pretty_json_size(packet) > ACTUAL_DEFAULT_MODEL_BEHAVIOR_HOT_PATH_JSON_BUDGET:
        raise ValueError("compaction-regression packet exceeds the hot-path budget")
    if contract.get("selected_todo_id") != expected_selected_todo_id:
        raise ValueError("compaction regression must preserve the selected todo")


def _scenario_contract(
    spec: _ScenarioSpec,
    source_packet: Mapping[str, Any],
    actor_packet: Mapping[str, Any],
) -> dict[str, Any]:
    if spec.actor_kind == "turn":
        build_model_behavior_actor_request(
            actor_packet,
            qualification_id=f"portfolio-preflight-{spec.scenario_id}",
            arm="full_packet",
            semantic_contract_required=False,
        )
        contract = _turn_expected_contract(source_packet)
        if _turn_expected_contract(actor_packet) != contract:
            raise ValueError(
                f"scenario {spec.scenario_id} actor packet diverges "
                "from source action contract"
            )
        if model_behavior_semantic_contract_from_packet(
            actor_packet,
            arm="full_packet",
        ) != model_behavior_semantic_contract_from_packet(
            source_packet,
            arm="full_packet",
        ):
            raise ValueError(
                f"scenario {spec.scenario_id} actor packet diverges "
                "from source semantic contract"
            )
    else:
        if spec.phase == "entry":
            _validate_actual_default_projection(actor_packet)
        build_onboarding_model_behavior_actor_request(
            actor_packet,
            qualification_id=f"portfolio-preflight-{spec.scenario_id}",
            phase=str(spec.phase),
        )
        contract = _semantic_contract(source_packet, phase=str(spec.phase))
        violations = _behavior_contract_violations(contract, phase=str(spec.phase))
        if violations:
            raise OnboardingActualBehaviorValidationError(
                "actual onboarding behavior violates stable invariants: "
                + ", ".join(violations)
            )
    if contract.get("decision", contract.get("route")) != spec.expected_route:
        raise ValueError(
            f"scenario {spec.scenario_id} does not produce {spec.expected_route}"
        )
    if (
        spec.scenario_id == "onboarding_agent_identity_gate"
        and contract.get("agent_id") is not None
    ):
        raise ValueError("identity-gate scenario must not preselect an agent")
    if (
        spec.scenario_id == "onboarding_goal_selection_gate"
        and contract.get("goal_id") is not None
    ):
        raise ValueError("goal-selection scenario must not preselect a goal")
    if spec.scenario_id == "turn_selected_todo" and not contract.get(
        "selected_todo_id"
    ):
        raise ValueError("selected-todo scenario requires selected work")
    if spec.scenario_id in {
        "turn_peer_agent_identity",
        "turn_same_agent_continuation",
    }:
        peer_route = model_behavior_semantic_contract_from_packet(
            source_packet,
            arm="full_packet",
        )["peer_route"]
        if not peer_route.get("agent_id"):
            raise ValueError("peer-agent scenario requires a selected agent identity")
        if peer_route.get("selected_todo_claimed_by") != peer_route.get("agent_id"):
            raise ValueError("peer-agent scenario must route work to the selected peer")
        if spec.scenario_id == "turn_same_agent_continuation":
            if peer_route.get("continuation_policy") != "same_agent_non_delivery":
                raise ValueError("same-agent scenario requires same_agent_non_delivery")
            if peer_route.get("same_agent_continuation") is not True:
                raise ValueError(
                    "same-agent scenario must preserve the completing peer"
                )
    if spec.scenario_id == "turn_human_gate":
        required = {
            "selected_todo_id": None,
            "user_action_required": True,
            "must_attempt_work": False,
            "delivery_allowed": False,
            "quiet_noop_allowed": False,
        }
        if any(contract.get(field) != value for field, value in required.items()):
            raise ValueError("human-gate scenario violates final gate precedence")
    if spec.scenario_id == "turn_required_vision_replan":
        semantics = model_behavior_semantic_contract_from_packet(
            source_packet,
            arm="full_packet",
        )
        vision = semantics["vision_continuation"]
        trigger_kinds = set(vision.get("trigger_kinds", []))
        required = {
            "selected_todo_id": None,
            "user_action_required": False,
            "must_attempt_work": True,
            "quiet_noop_allowed": False,
        }
        if any(contract.get(field) != value for field, value in required.items()):
            raise ValueError("required-vision scenario must execute before quiet wait")
        if vision.get("required") is not True or (
            "required_agent_vision_missing" not in trigger_kinds
        ):
            raise ValueError("required-vision scenario must preserve the profile gap")
        if not semantics["required_reads"]:
            raise ValueError("required-vision scenario must preserve required reads")
        if semantics["scheduler_action"].get("action") != "run_now":
            raise ValueError(
                "required-vision scenario must remain immediately runnable"
            )
    if spec.scenario_id == "turn_scoped_gate_successor_replan":
        signature = quota_action_signature_document(source_packet)
        action = dict(signature.get("action") or {})
        user = dict(signature.get("user") or {})
        selected = dict(action.get("selected_todo") or {})
        if not (
            user.get("action_required") is True
            and action.get("must_attempt") is True
            and action.get("delivery_allowed") is True
            and signature.get("response_plan") is None
            and selected.get("todo_id") == "todo_portfolio_deferred"
        ):
            raise ValueError(
                "scoped-gate scenario must notify without blocking successor replan"
            )
        semantics = model_behavior_semantic_contract_from_packet(
            source_packet,
            arm="full_packet",
        )
        if semantics["gate_or_stop"].get("interaction_mode") != (
            "scoped_user_gate_fallback"
        ):
            raise ValueError("scoped-gate scenario must preserve fallback mode")
        if semantics["scheduler_action"].get("action") != "run_now":
            raise ValueError("scoped-gate fallback must remain immediately runnable")
    if spec.scenario_id == "turn_capability_monitor_repair":
        signature = quota_action_signature_document(source_packet)
        capsule = dict(signature.get("contract_capsule") or {})
        lane = dict(capsule.get("work_lane_contract") or {})
        action = dict(signature.get("action") or {})
        interaction = dict(capsule.get("interaction_contract") or {})
        if not (
            interaction.get("mode") == "capability_bridge_repair"
            and action.get("must_attempt") is True
            and action.get("quiet_noop_allowed") is False
            and lane.get("must_attempt_work") is True
        ):
            raise ValueError(
                "capability gap must route the agent to a must-attempt "
                "capability bridge repair, not a monitor fallback or quiet wait"
            )
        capability_gate = source_packet.get("capability_gate")
        if not isinstance(capability_gate, dict) or capability_gate.get(
            "action"
        ) != "repair_bridge":
            raise ValueError(
                "capability gap must expose an agent-resolvable repair_bridge gate"
            )
        if "private_read" not in str(
            capability_gate.get("repair_missing") or []
        ):
            raise ValueError(
                "capability bridge repair must name the missing capability"
            )
        if "repair or materialize the missing bridge capability" not in str(
            action.get("primary_action")
        ):
            raise ValueError(
                "primary action must direct the agent to repair the bridge"
            )
    compaction_selected_todos = {
        "turn_quota_hot_path_compaction_regression": "todo_c0ffee123456",
        "turn_quota_hot_path_selected_todo_invariance": "todo_portfolio001",
        "turn_quota_hot_path_human_gate_invariance": None,
    }
    if spec.scenario_id in compaction_selected_todos:
        _validate_quota_hot_path_compaction_regression(
            source_packet,
            actor_packet,
            contract,
            expected_selected_todo_id=compaction_selected_todos[spec.scenario_id],
        )
    return contract


def _contrast_relation_failures(
    spec: _ContrastSpec,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> list[str]:
    failures = [
        f"expected_match:{field}"
        for field in spec.must_match_fields
        if left.get(field) != right.get(field)
    ]
    failures.extend(
        f"expected_difference:{field}"
        for field in spec.must_differ_fields
        if left.get(field) == right.get(field)
    )
    return failures


def _validate_contrast_source_contracts(
    contracts: Mapping[str, Mapping[str, Any]],
) -> None:
    scenario_ids = set(contracts)
    allowed_fields = set(_HARD_INVARIANT_FIELDS)
    for spec in _CONTRASTS:
        if spec.contrast_kind not in {"invariance", "sensitivity"}:
            raise ValueError(f"contrast {spec.contrast_id} has an invalid kind")
        if spec.left_scenario_id not in scenario_ids or spec.right_scenario_id not in (
            scenario_ids
        ):
            raise ValueError(
                f"contrast {spec.contrast_id} references an unknown scenario"
            )
        relation_fields = set(spec.must_match_fields) | set(spec.must_differ_fields)
        if not relation_fields or not relation_fields <= allowed_fields:
            raise ValueError(f"contrast {spec.contrast_id} has invalid relation fields")
        if set(spec.must_match_fields) & set(spec.must_differ_fields):
            raise ValueError(f"contrast {spec.contrast_id} has overlapping fields")
        failures = _contrast_relation_failures(
            spec,
            contracts[spec.left_scenario_id],
            contracts[spec.right_scenario_id],
        )
        if failures:
            raise ValueError(
                f"contrast {spec.contrast_id} source relation is invalid: "
                + ", ".join(failures)
            )


def _receipt_alignment(
    spec: _ScenarioSpec,
    receipt: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    if spec.actor_kind == "turn":
        fields = tuple(expected)
        mismatches = [
            f"source_mismatch:{field}"
            for field in fields
            if receipt.get(field) != expected[field]
        ]
        mismatches.extend(str(item) for item in receipt.get("safety_violations") or [])
    else:
        mismatches = []
        if receipt.get("next_action") != spec.expected_route:
            mismatches.append("next_action_mismatch")
        if receipt.get("source_aligned") is not True:
            mismatches.append("source_alignment_failed")
        mismatches.extend(str(item) for item in receipt.get("safety_violations") or [])
    return not mismatches, sorted(set(mismatches))


def _scenario_result(
    spec: _ScenarioSpec,
    packet: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    qualification_id: str,
    turn_actor: ModelBehaviorActor,
    onboarding_actor: OnboardingModelBehaviorActor,
) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
    receipt_digests: list[str] = []
    observed_routes: list[str] = []
    failure_codes: list[str] = []
    actor_error = False
    observations: list[dict[str, Any]] = []
    for repeat_index in range(ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS):
        run_id = f"{qualification_id}:{spec.scenario_id}:r{repeat_index + 1}"
        try:
            if spec.actor_kind == "turn":
                receipt = run_model_behavior_qualification_arm(
                    packet,
                    qualification_id=run_id,
                    arm="full_packet",
                    actor=turn_actor,
                    semantic_contract_required=False,
                )
                observed_route = str(receipt.get("decision") or "")
            else:
                receipt = run_onboarding_model_behavior_phase(
                    packet,
                    qualification_id=run_id,
                    phase=str(spec.phase),
                    actor=onboarding_actor,
                )
                observed_route = str(receipt.get("next_action") or "")
        except (ValueError, RuntimeError) as exc:
            failure_codes.append(_actor_failure_code(exc))
            actor_error = True
            break
        aligned, mismatches = _receipt_alignment(spec, receipt, expected)
        receipt_digests.append(_digest(dict(receipt)))
        observations.append(
            {field: receipt.get(field) for field in _HARD_INVARIANT_FIELDS}
        )
        if observed_route not in observed_routes:
            observed_routes.append(observed_route)
        if not aligned:
            failure_codes.extend(mismatches)
    repeats_completed = len(receipt_digests)
    passed = bool(
        not failure_codes
        and repeats_completed == ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS
    )
    return (
        {
            "scenario_id": spec.scenario_id,
            "actor_kind": spec.actor_kind,
            "phase": spec.phase,
            "expected_route": spec.expected_route,
            "status": "passed" if passed else "failed",
            "repeats_required": ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS,
            "repeats_completed": repeats_completed,
            "observed_routes": observed_routes,
            "failure_codes": sorted(set(failure_codes)),
            "receipt_digests": receipt_digests,
        },
        actor_error,
        observations,
    )


def _contrast_result(
    spec: _ContrastSpec,
    observations: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any]:
    left = observations.get(spec.left_scenario_id, [])
    right = observations.get(spec.right_scenario_id, [])
    compared = min(len(left), len(right))
    failure_codes: list[str] = []
    observation_digests: list[str] = []
    if compared != ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS:
        failure_codes.append("contrast_scenarios_incomplete")
    for repeat_index in range(compared):
        failures = _contrast_relation_failures(
            spec,
            left[repeat_index],
            right[repeat_index],
        )
        failure_codes.extend(failures)
        observation_digests.append(
            _digest(
                {
                    "left": dict(left[repeat_index]),
                    "right": dict(right[repeat_index]),
                }
            )
        )
    passed = bool(
        not failure_codes
        and compared == ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS
    )
    return {
        "schema_version": ACTUAL_DEFAULT_MODEL_BEHAVIOR_CONTRAST_SCHEMA_VERSION,
        "contrast_id": spec.contrast_id,
        "contrast_kind": spec.contrast_kind,
        "left_scenario_id": spec.left_scenario_id,
        "right_scenario_id": spec.right_scenario_id,
        "must_match_fields": list(spec.must_match_fields),
        "must_differ_fields": list(spec.must_differ_fields),
        "status": "passed" if passed else "failed",
        "repeats_required": ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS,
        "repeats_compared": compared,
        "failure_codes": sorted(set(failure_codes)),
        "observation_digests": observation_digests,
    }


def run_actual_default_model_behavior_portfolio(
    scenario_packets: Mapping[str, Mapping[str, Any]],
    *,
    scenario_sources: Mapping[str, Mapping[str, Any]],
    qualification_id: str,
    turn_actor: ModelBehaviorActor,
    onboarding_actor: OnboardingModelBehaviorActor,
) -> dict[str, Any]:
    """Run the fixed low-frequency one-arm portfolio with bounded receipts."""
    expected_ids = {spec.scenario_id for spec in _SCENARIOS}
    supplied_ids = set(scenario_packets)
    if supplied_ids != expected_ids:
        missing = sorted(expected_ids - supplied_ids)
        unknown = sorted(supplied_ids - expected_ids)
        raise ValueError(
            f"scenario packets must match the catalog; missing={missing}, unknown={unknown}"
        )
    source_ids = set(scenario_sources)
    if source_ids != expected_ids:
        missing = sorted(expected_ids - source_ids)
        unknown = sorted(source_ids - expected_ids)
        raise ValueError(
            "scenario sources must match the catalog; "
            f"missing={missing}, unknown={unknown}"
        )

    catalog = actual_default_model_behavior_scenario_catalog()
    contracts = {
        spec.scenario_id: _scenario_contract(
            spec,
            scenario_sources[spec.scenario_id],
            scenario_packets[spec.scenario_id],
        )
        for spec in _SCENARIOS
    }
    _validate_contrast_source_contracts(contracts)
    results: list[dict[str, Any]] = []
    observations: dict[str, list[dict[str, Any]]] = {}
    actor_call_count = 0
    aborted = False
    for spec in _SCENARIOS:
        if aborted:
            results.append(
                {
                    "scenario_id": spec.scenario_id,
                    "actor_kind": spec.actor_kind,
                    "phase": spec.phase,
                    "expected_route": spec.expected_route,
                    "status": "not_run",
                    "repeats_required": ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS,
                    "repeats_completed": 0,
                    "observed_routes": [],
                    "failure_codes": ["portfolio_aborted_after_actor_error"],
                    "receipt_digests": [],
                }
            )
            continue
        result, actor_error, scenario_observations = _scenario_result(
            spec,
            scenario_packets[spec.scenario_id],
            expected=contracts[spec.scenario_id],
            qualification_id=qualification_id,
            turn_actor=turn_actor,
            onboarding_actor=onboarding_actor,
        )
        actor_call_count += int(result["repeats_completed"])
        if actor_error:
            actor_call_count += 1
            aborted = True
        results.append(result)
        observations[spec.scenario_id] = scenario_observations

    contrast_results = [
        _contrast_result(spec, observations)
        for spec in _CONTRASTS
    ]
    passed = all(result["status"] == "passed" for result in results) and all(
        result["status"] == "passed" for result in contrast_results
    )
    scenario_failure_count = sum(
        result["status"] == "failed" for result in results
    )
    contrast_failure_count = sum(
        result["status"] == "failed" for result in contrast_results
    )
    skip_count = sum(result["status"] == "not_run" for result in results)
    return {
        "schema_version": ACTUAL_DEFAULT_MODEL_BEHAVIOR_PORTFOLIO_SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "topology": "actual_default_one_arm",
        "scenario_catalog_digest": _digest(catalog),
        "scenario_count": ACTUAL_DEFAULT_MODEL_BEHAVIOR_SCENARIO_COUNT,
        "contrast_count": ACTUAL_DEFAULT_MODEL_BEHAVIOR_CONTRAST_COUNT,
        "actor_call_budget": (
            ACTUAL_DEFAULT_MODEL_BEHAVIOR_SCENARIO_COUNT
            * ACTUAL_DEFAULT_MODEL_BEHAVIOR_REPEAT_ATTEMPTS
        ),
        "actor_call_count": actor_call_count,
        "failure_count": scenario_failure_count + contrast_failure_count,
        "skip_count": skip_count,
        "contrast_failure_count": contrast_failure_count,
        "qualification_passed": passed,
        "automatic_release_promotion_allowed": False,
        "scenarios": results,
        "contrasts": contrast_results,
        "boundary": {
            "tools_enabled": False,
            "raw_packets_persisted": False,
            "raw_model_responses_persisted": False,
            "automatic_retries": False,
        },
    }
