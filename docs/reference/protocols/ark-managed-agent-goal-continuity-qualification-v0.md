# Ark Managed Agent Goal Continuity Qualification v0

This protocol qualifies pause, replacement-session, and recoverable-failure
behavior when LoopX is driven by one Ark Managed Agent Goal activation. It
extends the one-shot host contract; it does not turn LoopX into the Goal
runtime and does not use LoopX Turn as an inner driver.

Continuity is not equivalent to keeping one host session alive. A valid
recovery reconstructs work from durable owners and treats the host session as
an execution envelope.

## State owners

| State | Authoritative owner | Recovery requirement |
| --- | --- | --- |
| Repository changes and validation artifacts | Project workspace | Reopen the same durable workspace or restore an explicit workspace checkpoint before doing more work. |
| Goal boundary, todo frontier, claims, evidence, quota, and leases | LoopX registry, active state, and event/runtime stores | Run a fresh `quota should-run`; never reconstruct the frontier from chat memory or an old prompt. |
| Installed LoopX CLI and workflow skills | One fixed installer release | Read back one CLI/skills revision. Codex and Managed Agent differ only in the installer target root. |
| Goal evaluation phase and terminal result | Goal host durable journal and event readback | Rehydrate before evaluating another completion. A journal existing on disk is not by itself proof that rehydration occurred. |
| Host session id and in-memory transcript | Host session | Non-authoritative. It may help locate events, but its survival is not a continuity requirement. |

## Recovery sequence

After a pause, host replacement, or ambiguous transport failure:

1. reopen the expected workspace and verify its repository identity;
2. run installer/doctor readback and reject mixed CLI/skill revisions;
3. read current LoopX status and run `quota should-run`;
4. reconcile the selected todo, claim or lease, evidence, and workspace diff;
5. inspect Goal-host events before retrying an activation whose admission is
   unknown;
6. regenerate the current `task_body` from LoopX state and submit it once only
   when the readback proves another activation is needed; and
7. require both validated LoopX writeback and Goal-host terminal evidence
   before calling the recovery complete.

The regenerated prompt may be textually identical when the durable frontier
has not changed. That is expected. Reusing an old prompt without the state and
quota read is not.

## Retry decisions

| Observation | Action |
| --- | --- |
| Transport failed before the host accepted the Goal and readback proves no Goal exists | Regenerate from current state, then submit once. |
| Admission is unknown, or host events show evaluation/work already started | Do not blindly resubmit. Read host events, workspace effects, and LoopX writeback first. |
| Worker wrote artifacts but durable todo evidence is absent | Validate the artifacts, then repair LoopX writeback without rerunning completed external effects. |
| LoopX todo is closed but Goal evaluation is still pending | Let the Goal runtime resume evaluation; do not reopen the completed todo. |
| Goal journal cannot be rehydrated or contradicts host events | Fail closed and preserve the workspace/frontier for diagnosis. |

Only idempotent reads are safe default retries. A retryable network error does
not make a Goal submission or repository mutation idempotent.

## Qualification stages

| Stage | Required evidence | Current deterministic seam |
| --- | --- | --- |
| A. LoopX frontier reconstruction | A replacement process selects the same todo and reads the latest durable note/evidence without an opaque host session handle. | `test_fresh_host_reconstructs_frontier_from_durable_loopx_state` |
| B. Workspace reconstruction | The replacement process observes the expected repository identity, diff, and validation artifacts. | Exercise in the representative issue-fix fixture. |
| C. Goal runtime rehydration | A restarted Goal host replays its journal, preserves the evaluation iteration, and reaches the next legal state without duplicate evaluation or follow-up. | Requires a host restart test; prompt or journal presence alone is insufficient. |
| D. Ambiguous-failure recovery | An authenticated canary interrupts after a known durable boundary, replaces the session, and reaches one terminal result without duplicate side effects. | Required before claiming full L3 continuity. |

Stage A proves that LoopX does not depend on host memory. It does not prove
Stages C or D. Full continuity requires all four stages.

Installation follows the fixed-script contract in
[`host-integration-surface-v0`](host-integration-surface-v0.md#ark-managed-agent-host).
Onboarding and doctor remain readback surfaces, not alternate installers.

## Focused check

```bash
python -m pytest -q tests/test_ark_managed_agent_host.py
```
