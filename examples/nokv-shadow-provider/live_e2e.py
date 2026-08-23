"""Repeatable live Stage-2 slice: production executor over file and NoKV providers.

This is the bounded live qualification the direction tracker asks for before
any provider promotion: the SAME invariant scenarios run against the
file-backed control provider and the live NoKV candidate, and the script
prints a compact public-safe pass/fail/unverified matrix. It is evidence
tooling, not a merge gate: without a reachable stack it reports every live
row as unverified and exits 0 only when nothing that DID run failed.

Environment (all required for the NoKV rows):
  NOKV_COORDINATION_LIVE=1
  NOKV_ETCD / NOKV_ETCD_PREFIX / NOKV_ROOT_ID
  NOKV_BUCKET / NOKV_OBJECT_ENDPOINT / NOKV_OBJECT_ROOT
  NOKV_OBJECT_KEY / NOKV_OBJECT_SECRET

Run from the repository root:
  python3 examples/nokv-shadow-provider/live_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loopx.control_plane.coordination.executor import (  # noqa: E402
    CoordinationAuthorityExecutor,
    sample_claim_envelope,
)
from loopx.control_plane.coordination.file_provider import (  # noqa: E402
    FileCoordinationProvider,
)
from loopx.control_plane.coordination.head import bootstrap_head  # noqa: E402

from provider import NoKVCoordinationProvider  # noqa: E402


def eligibility() -> dict:
    return {
        "authorization_projection_revision": 3,
        "authorization_projection_digest": "sha256:bootstrap-auth",
        "allowed_agent_ids": ["agent-a", "agent-b"],
        "dependencies_satisfied": True,
        "dependency_revision": 12,
        "gates_open": True,
        "gate_revision": 5,
    }


def todo() -> dict:
    return {
        "todo_revision": 7,
        "status": "open",
        "claimed_by": None,
        "eligibility": eligibility(),
        "repository": "git:example/repo",
        "code_revision": "0123456789abcdef",
        "last_lease_epoch": 6,
    }


def claim(executor, agent: str, todo_id: str, operation_id: str, ttl: int = 600):
    return executor.apply(
        sample_claim_envelope(
            goal_id=executor.goal_id,
            operation_id=operation_id,
            agent_id=agent,
            device_id=f"dev-{agent}",
            todo_id=todo_id,
            expected_todo_revision=7,
            expected_preconditions={
                "authorization_projection_revision": 3,
                "authorization_projection_digest": "sha256:bootstrap-auth",
                "dependency_revision": 12,
                "gate_revision": 5,
            },
            lease_ttl_seconds=ttl,
        )
    )


def scenario_matrix(make_provider) -> dict:
    """The shared invariant script, provider-agnostic. Returns row -> bool."""

    rows: dict[str, bool] = {}
    goal_id = "g" + uuid.uuid4().hex[:8]
    provider_a = make_provider(goal_id)
    provider_b = make_provider(goal_id)
    head = bootstrap_head(goal_id, {"todo-1": todo(), "todo-2": todo()})
    assert provider_a.load() == (None, 0)
    assert provider_a.compare_and_put(0, head)["result"] == "applied"
    executor_a = CoordinationAuthorityExecutor(
        provider_a, goal_id=goal_id, now=lambda: 1_800_000_000.0
    )
    executor_b = CoordinationAuthorityExecutor(
        provider_b, goal_id=goal_id, now=lambda: 1_800_000_000.0
    )

    # same-todo race with two independent handles and a real thread barrier
    barrier = threading.Barrier(2)
    outcomes: dict[str, dict] = {}

    def race(name, executor, agent):
        barrier.wait()
        outcomes[name] = claim(executor, agent, "todo-1", f"race-{agent}")

    threads = [
        threading.Thread(target=race, args=("a", executor_a, "agent-a")),
        threading.Thread(target=race, args=("b", executor_b, "agent-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    kinds = sorted(outcome["result"] for outcome in outcomes.values())
    rows["same_todo_one_winner"] = kinds == ["applied", "conflict"]

    winner = next(o for o in outcomes.values() if o["result"] == "applied")
    winner_agent = winner["original_receipt"]["actor"]["agent_id"]
    other_agent = "agent-b" if winner_agent == "agent-a" else "agent-a"

    # independent todo applies for the other endpoint after internal rebase
    second = claim(executor_b, other_agent, "todo-2", "independent-1")
    rows["independent_todo_applies"] = second["result"] == "applied"

    # exact replay across a reconstructed executor
    replay_executor = CoordinationAuthorityExecutor(
        make_provider(goal_id), goal_id=goal_id, now=lambda: 1_800_000_000.0
    )
    replayed = claim(replay_executor, winner_agent, "todo-1", f"race-{winner_agent}")
    rows["replay_returns_original_receipt"] = (
        replayed["result"] == "already_applied"
        and replayed["original_receipt"] == winner["original_receipt"]
    )

    # identity reuse with different semantics
    mutated = claim(
        replay_executor, winner_agent, "todo-1", f"race-{winner_agent}", ttl=601
    )
    rows["identity_mismatch_rejected"] = (
        mutated["result"] == "rejected"
        and mutated["reason"] == "operation_identity_mismatch"
    )

    # stale caller revision conflicts without state change
    head_now, generation_now = provider_a.load()
    stale = claim(executor_a, winner_agent, "todo-2", "stale-1")
    rows["stale_revision_conflicts"] = (
        stale["result"] == "conflict"
        and provider_a.load() == (head_now, generation_now)
    )

    # lost response after commit recovers through the receipt index
    class LossyOnce:
        def __init__(self, inner):
            self.inner = inner
            self.armed = True

        def load(self):
            return self.inner.load()

        def compare_and_put(self, expected, proposed):
            outcome = self.inner.compare_and_put(expected, proposed)
            if self.armed and outcome.get("result") == "applied":
                self.armed = False
                return {"result": "ambiguous"}
            return outcome

    lossy_executor = CoordinationAuthorityExecutor(
        LossyOnce(make_provider(goal_id)),
        goal_id=goal_id,
        now=lambda: 1_800_000_000.0,
    )
    goal2 = "g" + uuid.uuid4().hex[:8]
    provider2 = make_provider(goal2)
    provider2.compare_and_put(0, bootstrap_head(goal2, {"todo-1": todo()}))
    lossy2 = CoordinationAuthorityExecutor(
        LossyOnce(provider2), goal_id=goal2, now=lambda: 1_800_000_000.0
    )
    lost = claim(lossy2, "agent-a", "todo-1", "lost-1")
    rows["lost_response_recovers_receipt"] = lost["result"] == "already_applied"
    del lossy_executor

    final_head, _ = provider_a.load()
    rows["receipts_retained"] = len(final_head["receipt_index"]) == 2
    rows["authority_revision_advanced_twice"] = final_head["authority_revision"] == 2
    return rows


def file_matrix(root: Path) -> dict:
    return scenario_matrix(
        lambda goal_id: FileCoordinationProvider(root / "coordination", goal_id)
    )


def nokv_matrix() -> tuple[dict | None, str | None]:
    if os.environ.get("NOKV_COORDINATION_LIVE") != "1":
        return None, "NOKV_COORDINATION_LIVE unset"
    try:
        import nokv
    except ImportError:
        return None, "nokv SDK not installed"
    env = os.environ
    routing = nokv.RoutingConfig.etcd([env["NOKV_ETCD"]], env["NOKV_ETCD_PREFIX"], 10)

    def make_client():
        objects = nokv.ObjectStoreConfig.s3(
            env["NOKV_BUCKET"],
            region="us-east-1",
            root=env["NOKV_OBJECT_ROOT"],
            endpoint=env["NOKV_OBJECT_ENDPOINT"],
            access_key_id=env["NOKV_OBJECT_KEY"],
            secret_access_key=env["NOKV_OBJECT_SECRET"],
        )
        return nokv.Client(env["NOKV_ROOT_ID"], routing, objects)

    workbench = "wbstage2" + uuid.uuid4().hex[:10]
    make_client().create_workspace(workbench)

    def make_provider(goal_id):
        return NoKVCoordinationProvider(make_client(), workbench, goal_id)

    return scenario_matrix(make_provider), None


def main() -> int:
    matrix: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as root:
        matrix["file_provider"] = file_matrix(Path(root))
    nokv_rows, skip_reason = nokv_matrix()
    if nokv_rows is None:
        matrix["nokv_provider"] = {"unverified": skip_reason}
    else:
        matrix["nokv_provider"] = nokv_rows
        parity = {
            row: matrix["file_provider"].get(row) == value
            for row, value in nokv_rows.items()
        }
        matrix["file_nokv_parity"] = {
            "identical_row_outcomes": all(parity.values()),
            "rows": len(parity),
        }
    print(json.dumps(matrix, indent=2, sort_keys=True))
    failed = [
        f"{provider}.{row}"
        for provider, rows in matrix.items()
        for row, value in rows.items()
        if value is False
    ]
    if failed:
        print("FAILED rows:", failed, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
