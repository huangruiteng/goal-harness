#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_text = str(REPO_ROOT)
if sys.path[0] != repo_root_text:
    sys.path.insert(0, repo_root_text)

# The candidate checkout must win over any installed LoopX package.
from loopx.control_plane.testing.actual_default_model_behavior_portfolio import (
    build_actual_default_model_behavior_scenario_inputs,
    run_actual_default_model_behavior_portfolio,
)
from loopx.control_plane.testing.capability_monitor_repair_tool_behavior import (
    DoubaoCapabilityMonitorRepairToolBehaviorActor,
)
from loopx.control_plane.testing.doubao_model_behavior_actor import (
    DoubaoModelBehaviorActor,
    DoubaoOnboardingModelBehaviorActor,
)
from loopx.control_plane.testing.release_commit_qualification import (
    collect_release_source_identity,
)
from loopx.control_plane.testing.replan_evidence_tool_behavior import (
    DoubaoReplanEvidenceToolBehaviorActor,
)
from loopx.control_plane.testing.scoped_gate_successor_tool_behavior import (
    DoubaoScopedGateSuccessorToolBehaviorActor,
)
from loopx.control_plane.testing.selected_todo_tool_behavior import (
    DoubaoSelectedTodoToolBehaviorActor,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the actual-default behavior portfolio against the real Ark "
            "Doubao API and print only its bounded receipt."
        )
    )
    parser.add_argument("--qualification-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    args = _parser().parse_args()
    source = collect_release_source_identity(args.repo_root)
    if source["git_dirty"]:
        raise RuntimeError(
            "live Doubao qualification requires a clean candidate checkout"
        )
    turn_actor = DoubaoModelBehaviorActor.from_environment(
        timeout_seconds=args.timeout_seconds
    )
    onboarding_actor = DoubaoOnboardingModelBehaviorActor.from_environment(
        timeout_seconds=args.timeout_seconds
    )
    selected_todo_actor = DoubaoSelectedTodoToolBehaviorActor.from_environment(
        timeout_seconds=args.timeout_seconds
    )
    replan_evidence_actor = DoubaoReplanEvidenceToolBehaviorActor.from_environment(
        timeout_seconds=args.timeout_seconds
    )
    scoped_gate_successor_actor = (
        DoubaoScopedGateSuccessorToolBehaviorActor.from_environment(
            timeout_seconds=args.timeout_seconds
        )
    )
    capability_monitor_repair_actor = (
        DoubaoCapabilityMonitorRepairToolBehaviorActor.from_environment(
            timeout_seconds=args.timeout_seconds
        )
    )
    with TemporaryDirectory(prefix="loopx-doubao-live-") as temp_dir:
        temp_root = Path(temp_dir)

        def qualify_selected_todo(run_id: str) -> dict[str, object]:
            run_digest = sha256(run_id.encode("utf-8")).hexdigest()[:16]
            return selected_todo_actor.qualify(
                qualification_id=run_id,
                fixture_root=temp_root / "selected-todo" / run_digest,
            )

        def qualify_replan_evidence(run_id: str) -> dict[str, object]:
            run_digest = sha256(run_id.encode("utf-8")).hexdigest()[:16]
            return replan_evidence_actor.qualify(
                qualification_id=run_id,
                fixture_root=temp_root / "replan-evidence" / run_digest,
            )

        def qualify_scoped_gate_successor(run_id: str) -> dict[str, object]:
            run_digest = sha256(run_id.encode("utf-8")).hexdigest()[:16]
            return scoped_gate_successor_actor.qualify(
                qualification_id=run_id,
                fixture_root=temp_root / "scoped-gate-successor" / run_digest,
            )

        def qualify_capability_monitor_repair(run_id: str) -> dict[str, object]:
            run_digest = sha256(run_id.encode("utf-8")).hexdigest()[:16]
            return capability_monitor_repair_actor.qualify(
                qualification_id=run_id,
                fixture_root=temp_root / "capability-monitor-repair" / run_digest,
            )

        sources, packets = build_actual_default_model_behavior_scenario_inputs(
            temp_root / "portfolio"
        )
        result = run_actual_default_model_behavior_portfolio(
            packets,
            scenario_sources=sources,
            qualification_id=args.qualification_id,
            turn_actor=turn_actor,
            onboarding_actor=onboarding_actor,
            selected_todo_actor=qualify_selected_todo,
            replan_evidence_actor=qualify_replan_evidence,
            scoped_gate_successor_actor=qualify_scoped_gate_successor,
            capability_monitor_repair_actor=qualify_capability_monitor_repair,
        )
    result["source"] = source
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["qualification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
