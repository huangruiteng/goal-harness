#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_text = str(REPO_ROOT)
if sys.path[0] != repo_root_text:
    sys.path.insert(0, repo_root_text)

# The candidate checkout must win over any installed LoopX package.
from loopx.control_plane.testing.actual_default_model_behavior_portfolio import (  # noqa: E402
    build_actual_default_model_behavior_scenario_inputs,
    run_actual_default_model_behavior_portfolio,
)
from loopx.control_plane.testing.doubao_model_behavior_actor import (  # noqa: E402
    DoubaoModelBehaviorActor,
    DoubaoOnboardingModelBehaviorActor,
)
from loopx.control_plane.testing.release_commit_qualification import (  # noqa: E402
    collect_release_source_identity,
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
    with TemporaryDirectory(prefix="loopx-doubao-live-") as temp_dir:
        sources, packets = build_actual_default_model_behavior_scenario_inputs(
            Path(temp_dir)
        )
        result = run_actual_default_model_behavior_portfolio(
            packets,
            scenario_sources=sources,
            qualification_id=args.qualification_id,
            turn_actor=turn_actor,
            onboarding_actor=onboarding_actor,
        )
    result["source"] = source
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["qualification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
