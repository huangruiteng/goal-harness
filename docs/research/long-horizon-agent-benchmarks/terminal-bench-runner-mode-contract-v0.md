# Terminal-Bench Runner Mode Contract V0

Checked at: 2026-06-08T18:48:19+08:00.

This note answers the core Goal Harness research runner-integration question for
`goal-harness benchmark run terminal-bench ...`: the current core comparison is
`hardened-codex` versus `codex-goal-harness`. The first arm is the true Codex
baseline for this Goal Harness experiment because it keeps the same hardened
install surface but injects no Goal Harness state. The second arm is the
`Codex + Goal Harness` treatment.

This is a no-run contract. It does not run Harbor, Terminal-Bench, Docker,
Codex, model APIs, cloud sandboxes, paid compute, uploads, shares, or
leaderboard paths.

## Layers

| Layer | Meaning | May affect official task semantics |
| --- | --- | --- |
| Parent runner control plane | Select task slice, create run id, recheck quota/gates, invoke Harbor, ingest structured results, write compact Goal Harness history. | No |
| Hardened Codex baseline | Run the same hardened Codex worker install with the original task prompt and no Goal Harness packet, skill, CLI bridge, or state. | No |
| Goal Harness treatment worker | Give the worker Goal Harness todo/state/checkpoint/replan surfaces and evaluate `Codex + Goal Harness` as the agent-harness pair. | Yes, as the core experimental mode |

The parent runner control plane may exist for all modes. The important
question is whether the benchmark case itself receives Goal Harness-managed
context or intervention.

## Modes

The future CLI should expose explicit modes:

```text
goal-harness benchmark run terminal-bench \
  --mode hardened-codex | codex-goal-harness
```

| Mode | Case worker | Goal Harness around case | Goal Harness inside case | Primary use |
| --- | --- | --- | --- | --- |
| `hardened-codex` | Goal Harness-managed Codex worker install, but the task prompt is unchanged and access packet mode is `none`. | Parent runner only. | None. | True Codex baseline for this experiment under the hardened install surface. |
| `codex-goal-harness` | The same hardened Codex worker receives the Goal Harness access packet/bridge surface. | Parent runner plus managed checkpoints/writeback. | Yes: todo/state/checkpoint/replan may be available. | Core Goal Harness experiment: the `Codex + Goal Harness` agent-harness pair. |

`hardened-codex` is not a native Codex leaderboard baseline because the install
surface is intentionally hardened. It is, however, the right paired baseline for
Goal Harness uplift analysis because it shares the same custom agent install
surface as `codex-goal-harness` while withholding Goal Harness state.

`codex-goal-harness` is intentionally a different agent mode. It may
still use the benchmark's official verifier, but it must be reported as
`worker_mode=codex_goal_harness_cli` or equivalent. Its result is not a native
Codex CLI baseline.

## Why Not Keep Bare Codex

The old `bare-codex` path tested Harbor's native `--agent codex` startup
surface. It is no longer a primary baseline because the Goal Harness treatment
requires the hardened custom agent install. Comparing treatment against native
Harbor Codex would mix install/startup differences with harness effects.

Keep native/bare evidence only as legacy startup debugging if an existing run
already produced it. Do not launch it as part of the current main protocol.

Run both arms in parallel on the same selected hard task whenever resources
allow. That makes task drift, verifier drift, and runner conditions easier to
compare.

## Per-Case Invariants

For `hardened-codex`, each case must preserve:

- benchmark task prompt unchanged;
- tests, scoring, resources, timeout, dataset, and runner source unchanged;
- same model, auth strategy, and hardened install strategy unless an ablation
  field records the change;
- no Goal Harness review-packet, active-state, todo, report, or checkpoint text
  injected into the benchmark task instruction;
- no upload, share, publish, or leaderboard flag unless a separate publication
  gate is explicitly opened;
- raw logs, raw Codex sessions, Docker logs, local paths, auth material, and
  task artifacts remain private.

For `codex-goal-harness`, each case must additionally record:

- `case_semantics_changed_by_harness=true`;
- the Goal Harness state surfaces available to the worker;
- intervention/checkpoint/replan counts;
- human or simulator intervention policy if present;
- claim boundary that this is a `model + harness` pair, not native Codex.

## Event Fields

Compact benchmark events should include these mode fields:

| Field | Example |
| --- | --- |
| `runner_control_plane` | `goal_harness_parent_runner` |
| `worker_mode` | `hardened_codex_baseline` or `codex_goal_harness_cli` |
| `case_semantics_changed_by_harness` | `false` for hardened baseline, `true` for treatment |
| `goal_harness_inside_case` | `false` for hardened baseline, `true` for treatment |
| `official_score_comparable_to_native_codex` | `false` for both current arms |
| `official_score_comparable_to_goal_harness_treatment` | `true` for the hardened baseline |
| `control_plane_score_applicable` | `false` for hardened baseline, `true` for treatment |
| `leaderboard_evidence` | `false` until an explicit publication gate exists |

## Recommended Implementation Order

1. Implement the hardened Codex baseline no-run fixture and command envelope.
2. Implement the `codex-goal-harness` worker bridge fixture and command
   envelope.
3. Implement the private no-upload runner wrapper with the two primary modes.
4. Run paired parallel hard-task experiments and compare score, closure,
   counters, and wall-time policy.

## Stop Conditions

Stop before:

- reintroducing `bare-codex` as a primary baseline;
- injecting Goal Harness state into a hardened baseline case;
- calling `codex-goal-harness` a native Codex baseline;
- running full `terminal-bench@2.0`;
- adding upload/share/leaderboard behavior;
- copying credentials, raw logs, raw sessions, Docker logs, host paths, or task
  artifacts into public artifacts;
- claiming official leaderboard uplift, benchmark pass/fail improvement, or
  paper-ready evidence from this contract.

## Smoke

```bash
python3 examples/terminal-bench-runner-mode-contract-smoke.py
```

The smoke validates the document, constructs the mode contract payload, checks
the per-mode semantics flags, and proves the contract remains public-safe and
no-run/no-submit.
