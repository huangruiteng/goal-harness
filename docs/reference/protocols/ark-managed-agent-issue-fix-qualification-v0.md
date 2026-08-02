# Ark Managed Agent Issue-Fix Qualification v0

This protocol qualifies LoopX issue-fix work when one LoopX goal prompt is
submitted to an Ark Managed Agent Goal host. It composes existing issue-fix
and host contracts; it does not introduce another runtime or another prompt
family.

The qualification is deliberately staged. A repaired file is useful evidence,
but it is not proof that the Goal host reached a durable terminal state.

## Evidence stages

| Stage | Required evidence | Pass condition |
| --- | --- | --- |
| 1. Intake and route | Public-safe issue metadata and an `issue_fix_feasibility_v0` packet | Exactly one route is selected. A `fix_pr` route has a named repro, bounded scope, and named validation. |
| 2. Worker repair | Repro-before, minimal patch, focused validation-after, and changed-file summary | The repro fails before the patch, validation passes after it, and the artifact is review-ready without claiming an external write. |
| 3. Durable LoopX closure | Validated todo writeback plus explicit successor or `no_followup` | The selected todo is durably closed and a new `quota should-run` no longer asks the worker to repeat the repair. |
| 4. Goal host closure | Host events for Goal evaluation and terminal session state | Evaluation ends satisfied, the Goal becomes achieved, and the session returns idle without a provider, evaluator, or transport error. |
| 5. Review handoff | Review packet and explicit authority state | The packet is ready for review. PR creation, review request, merge, and publish remain false until separately authorized. |

Stages 1–3 qualify the issue-fix worker path. Stages 1–4 qualify the one-shot
Goal host path end to end. Stage 5 qualifies the handoff boundary; it does not
grant publication authority.

## Verdict rules

Use these verdicts instead of one overloaded success bit:

| Observed result | Worker verdict | Goal-host verdict | Meaning |
| --- | --- | --- | --- |
| Repro, patch, validation, and durable todo closure all pass; Goal evaluation ends satisfied | pass | pass | End-to-end host case passed. |
| Worker evidence passes; Goal evaluator or provider fails before satisfied | pass | fail | The repair is real, but the host case is not complete. Diagnose the evaluator/provider boundary. |
| Code changes, but focused validation or durable writeback is missing | fail | not reached | Do not treat a plausible diff as a completed issue fix. |
| Goal reports satisfied without a validated repair artifact | fail | invalid | The evaluator result is insufficient and the case must be rejected. |
| Review packet is ready but external-write authority is absent | pass | pass or not applicable | Stop at draft/review handoff; do not publish. |

`issue_fix_validated_fix_artifact_v0` intentionally owns worker evidence only.
It does not contain a Goal terminal-state field. Goal satisfaction must come
from the host event stream or an equivalent host readback, never from the
presence of a patch.

## Representative matrix

An L2 qualification run should cover more than one happy-path issue:

1. a bounded issue that selects `fix_pr`, reproduces locally, applies a minimal
   patch, and passes focused validation;
2. an issue with useful diagnosis but insufficient repair evidence that routes
   to `comment_only` and remains externally gated;
3. an issue with neither a safe repair nor useful comment payload that routes
   to `triage_only` with no fabricated follow-up;
4. a one-shot Goal-host run using the same generated `task_body` as the cloud
   host, including durable todo closure and terminal Goal readback; and
5. a review-ready handoff that proves no comment, PR, merge, or publish action
   occurred without authority.

The deterministic repository fixture covers the repair mechanics. At least
one authenticated host run is still required for stage 4; a mock provider or a
successful patch alone cannot close that requirement.

## Current live finding

A fresh Goal-host parity replay installed the CLI and workflow skills from one
clean revision, then submitted one generated task body. The real issue-fix
worker reproduced the retry-delay defect, applied the one-line repair, passed
all four focused tests, wrote the review handoff, and closed its LoopX todo
with explicit `no_followup`.

The next quota read returned `terminal_no_followup` with complete user and
agent todo sources and no acceptance gaps. A state-aware Goal evaluator then
observed that durable terminal state, emitted a satisfied evaluation, and the
session returned idle. The run completed 14 authenticated provider exchanges.
The correct classification is therefore
`repair=pass, durable_closure=pass, goal_host=pass`; publication remains a
separate gated handoff.

Private prompts, credentials, provider payloads, local paths, and raw traces
are intentionally excluded from this public protocol.

## Durable checks

Run the focused contract:

```bash
python -m pytest -q tests/test_ark_managed_agent_issue_fix_matrix.py
```

The test composes the current feasibility, deterministic repair, Goal-host,
and review-handoff contracts. It also prevents the validated repair artifact
from silently acquiring or implying Goal terminal-state authority.
