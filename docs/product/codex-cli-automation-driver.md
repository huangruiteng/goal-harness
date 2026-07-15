# Codex CLI Adapter for LoopX Turn

Status: experimental product route and implementation audit.

The product goal is one reusable mechanism: LoopX CLI decides what may run,
Codex CLI performs one bounded agent turn, and LoopX validates and records the
outcome. It should approach the control-plane behavior available in Codex App
without copying App-specific heartbeat logic or turning Codex session files
into project state.

The host-neutral lifecycle is defined by
[`loopx_turn_v0`](../reference/protocols/loopx-turn-v0.md). This page records
the Codex CLI adapter policy and the current parity gap.

## Current Verdict

The repository has useful Codex CLI probes and wrappers, but they are not yet a
complete LoopX Turn adapter.

Reusable pieces include:

- `codex-cli-session-probe` for help-only capability discovery;
- visible-session proof and runtime-idle checks;
- `codex-cli-local-scheduler-tick` for a no-execution candidate/blocker packet;
- `codex-cli-local-scheduler-exec` for explicit prefix-gated command execution;
  and
- strong transcript, credential, session-file, and hidden-fallback boundaries.

The outer orchestration is incomplete. A current dry-run scheduler tick can
route visible-session proof blockers, but it does not itself:

- read a live `quota should-run --turn-envelope` decision;
- pass observed tool capabilities into that decision;
- preserve the selected todo and claim/continuation contract;
- enforce the workspace guard before host execution;
- receive a typed task result and validate it;
- perform idempotent todo/state writeback followed by one quota spend; or
- apply and acknowledge the resulting scheduler state.

Therefore the existing `codex-cli-local-scheduler-*` commands should be treated
as adapter probes, not advertised as App-parity automation. Their session proof,
idle, prefix, and privacy checks should be reused behind a smaller host-neutral
driver.

## Codex App Parity Matrix

| Capability | Codex App baseline | Current Codex CLI route | v0 driver requirement |
| --- | --- | --- | --- |
| Persistent identity | Automation thread plus registered LoopX agent | Goal and agent ids exist; resume handle is only a host candidate | Keep `(goal, agent, todo)` authoritative and session handle opaque/local |
| Wake and resume | Heartbeat wakes the existing thread | External scheduler can emit a resume candidate after proof | Start or resume one bounded turn with typed timeout/failure |
| Fresh control decision | Agent runs live `quota should-run` and follows `interaction_contract` | Tick accepts an optional quota fixture and otherwise has no live decision | Run live TurnEnvelope decision on every tick; fixtures only for tests |
| User gate | Concrete projected action is shown; host work stops | Proof blocker is modeled, but current LoopX user gate is not routed by the tick | Route exact user action without invoking Codex or spending |
| Todo continuation | Selected todo, claim, continuation, and successor policy survive turns | Not part of scheduler tick | Preserve todo id and apply claim/complete/successor transitions |
| Tool capability | Observed capabilities are passed to quota routing | Codex help probe is not projected into capability routing | Declare observed capabilities; use capability repair rather than user gates |
| Workspace isolation | Agent obeys workspace guard and repository policy | Not enforced by scheduler tick | Stop or relocate before repository writes |
| Bounded execution | Heartbeat prompt asks for one validated segment | Candidate command execution exists, but no task result contract | Require typed result with bounded timeout and no silent mode fallback |
| Validation and writeback | Validate, refresh, then spend one slot | Wrapper intentionally does not validate or spend | Validate artifact, write idempotently, then spend exactly once |
| Scheduler/backoff | App RRULE is applied and acknowledged without spend | Tick can render cadence only when a quota fixture supplies it | Apply and ack live scheduler hint, including failure recovery |
| Repair/replan | Typed control state can preserve, repair, or replace the current route | Existing decisions describe session proof only | Distinguish `repair_required` from `replan_required`; terminate only on acceptance or explicit stop |
| Privacy | Raw host material stays outside LoopX state | Existing boundaries are strong | Preserve current boundary and add a typed result channel |

This matrix is an implementation checklist, not evidence that the capabilities
already match.

## Product Shape

The experimental user-facing surface should converge on one command group:

```bash
loopx turn diagnose \
  --project . \
  --goal-id <goal-id> \
  --agent-id <agent-id> \
  --host codex-cli

loopx turn run-once \
  --project . \
  --goal-id <goal-id> \
  --agent-id <agent-id> \
  --host codex-cli \
  --execution-mode interactive-visible
```

This is an implementation target, not a shipped command. The first command
should report host capability and parity gaps without execution. The second
should compose a live LoopX decision, one Codex turn, typed closeout,
validation, writeback, spend, and scheduler acknowledgement.

Codex CLI policy supports two explicit modes:

- `interactive-visible` is the normal product route. The user can see,
  interrupt, and take over the turn. Missing idle or attach proof stops the
  tick.
- `isolated-headless` is an explicit experimental worker or benchmark route.
  It uses an isolated workspace and never claims to preserve the visible TUI.

The driver must never switch from `interactive-visible` to
`isolated-headless` as a fallback. This preserves the existing `/goal`
visible-first promise while allowing controlled non-interactive dogfood to test
the host-neutral mechanism.

## Run-once Algorithm

```text
1. Resolve project, goal, registered agent, execution mode, and Codex capability.
2. Run live quota should-run --turn-envelope with observed capabilities.
3. Route user notification, quiet wait, repair, or delivery exactly as decided.
4. Claim/preserve the selected todo and satisfy workspace guard.
5. Start or resume one Codex turn with the thin task body and TurnEnvelope.
6. Require a typed result; validate the material artifact or state change.
7. Update/complete the todo or write a repair/replan delta; refresh state.
8. Spend once only for validated delivery; apply and ack scheduler state.
```

The host adapter may use existing session proof, runtime idle, timeout, and
command-prefix helpers. It should not make callers assemble the old probe chain
manually.

## Typed Repair And Replan

LoopX Turn uses typed repair when the current todo is still correct but the
host, workspace, capability, validation, or writeback path is recoverable. It
uses typed replan when the route itself is no longer a valid way to close the
goal acceptance gap.

Replan is triggered by any of these conditions:

- the active vision remains open but no runnable todo exists;
- negative evidence invalidates the selected route;
- host capabilities make the todo non-executable and repair would change its
  intent; or
- two eligible turns repeat the same no-progress result.

A replan turn must write a bounded todo delta or vision replan trigger. If it
cannot produce a material delta, it returns a concrete blocker instead of
polling indefinitely.

## Experimental Stages

1. **Contract**: land the host-neutral lifecycle and this parity matrix.
2. **Shadow**: feed real TurnEnvelope decisions through a no-execution adapter
   and compare action signatures and typed routes.
3. **One turn**: run a real Codex CLI turn in an explicit mode, require typed
   result, validate, write back, and prove spend ordering.
4. **Scheduled continuation**: prove resume/new-session policy, stateful
   backoff, acknowledgement, retries, and no duplicate spend.
5. **Benchmark dogfood**: compare the driver with Codex App and the canonical
   countable `/goal` baseline under matched source, budget, concurrency,
   no-feedback, no-sync, no-upload, and no-submit boundaries.
6. **Promotion review**: decide whether to keep the adapter experimental,
   replace old probe entry points, or generalize LoopX Turn to another CLI
   host.

Benchmark dogfood records compact parity, trajectory, and closeout evidence. It
must not commit raw task text, raw trajectories, verifier output, credentials,
or local artifact paths.

## Rollback And Non-goals

The adapter must be disableable without changing LoopX goal state, normal CLI
commands, or Codex App heartbeat operation. Old probe commands may remain as
diagnostics until the consolidated driver covers their durable boundaries; they
must not be the default product narrative.

This route does not:

- replace Codex App before measured parity evidence exists;
- make Codex CLI session data authoritative;
- silently answer user gates or handle credentials;
- launch benchmark jobs, upload artifacts, or submit leaderboard results; or
- treat process exit zero, generated prose, or a session resume as validated
  task progress.
