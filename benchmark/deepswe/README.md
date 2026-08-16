# DeepSWE practice

This note generalizes the current DeepSWE pilot without publishing task text,
case-specific trajectories, verifier output, credentials, local paths, private
runner details, or unqualified score claims.

## Research question

Compare the same model on the same pinned DeepSWE task under two harness arms:

- baseline: native Codex Goal with no LoopX state or continuation protocol;
- treatment: the preregistered LoopX product path.

The comparison is about harness value, not a model-only leaderboard result.
Every claim remains scoped to the pinned task set, runner, model, permissions,
budget, and verifier.

## Frozen selection and replacement

Freeze candidate order before observing new outcomes. Screen baseline cases in
that order with concurrency one and the preregistered retry policy. A candidate
enters the treatment tranche only when the baseline attempt is countable and
its official outcome satisfies the preregistered selection rule.

Infrastructure, setup, agent-start, terminal-closeout, or verifier failures are
not scored task failures. Replace an uncountable attempt with the next case from
the frozen queue. Do not rerun a case after its verifier result has informed the
controller, and never select replacements by browsing raw task or solution
artifacts.

## Native Goal proof

The baseline must use the Codex app-server Goal API, not `codex exec`, a prompt
whose first token is `/goal`, or an outer polling loop labeled as Goal mode.
The transaction is:

```text
initialize(experimentalApi=true)
  -> initialized
  -> thread/start
  -> thread/goal/set(status=active)
  -> thread/goal/get
  -> turn/start
  -> observe correlated turn terminal event
  -> thread/goal/get
  -> while Goal remains active, observe the next automatic continuation turn
  -> stop only after Goal leaves active or the shared Goal timeout expires
  -> stop worker
  -> independent verifier
```

`turn/start` acceptance is not completion. The benchmark host must continue
serving any environment bridge while it drains app-server events. It starts
only the initial task turn; Codex owns automatic continuation turns while the
Goal remains active. If the response turn id and event-stream turn id differ,
the event-stream id becomes canonical. The installed transaction, stdio
transport, event reducer, and receipt live in
[`benchmark_toolkit.native_codex_goal`](../../loopx/capabilities/benchmark_toolkit/native_codex_goal.py).
[`../native_codex_goal.py`](../native_codex_goal.py) is intentionally only a
compatibility import, so runner code and examples cannot drift into a second
implementation.

### Real Codex connection

The runnable example calls `codex app-server --listen stdio:// --enable goals`,
performs the transaction above, and prints only a compact receipt. Keep the
objective and task in files so raw text is not duplicated into command history:

```bash
python benchmark/deepswe/run_native_codex_goal.py \
  --cwd <task-worktree> \
  --objective-file <objective.txt> \
  --task-file <task.txt> \
  --model <model-route>
```

Use `--preflight-only` to verify initialize, thread creation, and Goal
attachment without starting a model turn. A benchmark adapter can reuse the
same runtime directly while keeping its environment bridge active in another
task:

```python
from loopx.capabilities.benchmark_toolkit.native_codex_goal import (
    NativeGoalConfig,
    run_native_goal_process_until_terminal,
)

turn = run_native_goal_process_until_terminal(
    NativeGoalConfig(
        cwd=task_worktree,
        objective=objective,
        task_instruction=instruction,
        model=model,
        sandbox_policy=runner_owned_sandbox_policy,
    ),
    process_command=runner_owned_isolated_app_server_command,
    process_env=runner_owned_environment,
    process_cwd=runner_control_directory,
    goal_timeout_sec=timeout_seconds,
)
```

The imported runtime owns no evaluator access, task command bridge, credential
policy, or score authority. Those remain explicit runner responsibilities. A
separate `process_cwd` is useful when the Goal-visible `cwd` exists only inside
the runner's mount namespace.

## Authority and anti-cheating

Both arms receive the same task-visible filesystem, network, sandbox, approval
policy, model credential envelope, and tool surface. Neither arm may read:

- evaluator answers, hidden references, verifier source, or expected patches;
- another trial's workspace, state, or trajectory;
- controller-private manifests or evidence;
- official reward or verifier feedback during the agent phase.

A private structured audit checks observed tool access against runner-owned
isolation attestations. The public receipt contains only stable labels, counts,
digests, and reason codes. Integrity qualification and treatment fidelity are
separate gates: a clean run can still be uncountable when the treatment did not
execute the preregistered LoopX path.

## Preflight and lifecycle

Before each launch, a no-agent preflight must prove:

- pinned runner and task-set revisions;
- exact case and arm identity;
- model, effort, time, token, concurrency, and retry envelope;
- answer/verifier denial and cross-trial isolation;
- no-upload and no-submission policy;
- worker-before-verifier ordering;
- compact result and terminal-closeout destinations.

The runner owns task execution and verifier invocation. LoopX settlement occurs
only after controller validation of a compact terminal result. A successful
state write, Todo transition, or quota spend cannot turn an invalid benchmark
attempt into evidence.

## Public evidence

Record enough compact information to reproduce classification without exposing
protected material:

- manifest and runner revision digests;
- arm, model, effort, budget, retry, and permission labels;
- lifecycle phase and failure attribution;
- native Goal method/status evidence;
- integrity and treatment-fidelity dispositions;
- official score only after independent scoring and countability checks.

Keep raw tasks, trajectories, tool arguments, logs, diffs, credentials,
verifier output, private audit references, and local paths in ignored private
storage. Promote concrete result tables only after the matched study is solid
enough to support the stated claim level.
