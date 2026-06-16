# Contributor Task Board

This board is the public, contributor-facing projection of Goal Harness work.
It is intentionally different from `.local` active goal state:

- this file lists public work that can be discussed, claimed, reviewed, and
  validated in the repository;
- `.local`, `.goal-harness`, and live `ACTIVE_GOAL_STATE.md` files remain local
  runtime data for maintainers and automation;
- private benchmark traces, verifier output, raw agent sessions, credentials,
  internal document links, and local machine paths must not be copied here.

The goal is to make important work discoverable without turning the repository
into a mirror of maintainer scratch state.

## Status Legend

| Status | Meaning |
| --- | --- |
| Available | Ready for someone to comment on the linked issue or open a small PR. |
| Claimed | Someone has said they are working on it, or a maintainer assigned it. |
| Maintainer-owned | Active work is happening in maintainer/local automation; ask before touching. |
| Needs design | Discussion is welcome, but implementation needs agreement first. |
| Blocked | Waiting on a decision, dependency, or maintainer writeback. |
| Done | Completed and ready to archive from this board. |

## How To Claim Work

1. Prefer a linked GitHub issue. If there is no issue yet, open one with the
   contributor task template.
2. Comment that you would like to work on the task. Maintainers will mark it
   `claimed` or suggest a smaller slice.
3. For docs-only typo fixes or obviously tiny cleanups, opening a direct PR is
   fine.
4. If a claimed task has no update for 14 days, maintainers may release it back
   to `Available` after one ping.
5. If a task is `Maintainer-owned`, do not duplicate the work. Ask whether
   there is a public helper slice instead.

## Current Public Tasks

| ID | Status | Area | Good first? | Scope | Owner / issue | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| GH-C01 | Available | docs | Yes | Add a short "first goal" walkthrough that starts with `goal-harness demo`, inspects status/history, completes one todo, and shows the next todo. Keep it public and runnable on a clean checkout. | Unclaimed | `goal-harness check --scan-path README.md --scan-path docs/ --scan-path examples/` |
| GH-C02 | Available | tests | Yes | Add or extend a focused smoke test around todo archive/completion behavior. Prefer copying the style of `examples/todo-lifecycle-cli-smoke.py`. | Unclaimed | `python3 examples/todo-lifecycle-cli-smoke.py` and `python3 -m py_compile goal_harness/*.py` |
| GH-C03 | Available | diagnostics | No | Improve duplicate run-history index diagnostics so `goal-harness check` gives the next repair action, not only a warning. Include a small fixture or smoke path if practical. | Unclaimed | `goal-harness check --scan-root .` plus focused smoke if added |
| GH-C04 | Available | docs | Yes | Improve README troubleshooting for install, PATH setup, canary/default wrappers, and `goal-harness doctor`. | Unclaimed | `goal-harness check --scan-path README.md --scan-path CONTRIBUTING.md` |
| GH-C05 | Maintainer-owned | benchmark | No | Long-horizon benchmark evidence program, including runner contracts, trace retention, and score accounting. External contributors should not run private/local benchmark artifacts or duplicate live case runs unless maintainers split out a public issue. | Maintainers | Maintainer-run benchmark ledger and public/private scan |
| GH-C06 | Maintainer-owned | control plane | No | Heartbeat, quota, and status projection contracts that affect active local automations. Contributions need an issue and maintainer ack before implementation. | Maintainers | Contract smokes plus maintainer automation dry run |
| GH-C07 | Needs design | coordination | No | Public design discussion for task claims, leases, and frontstage contributor views. Implementation should wait for an agreed first slice. | Unclaimed | Design note or issue accepted by maintainers |

## Suggested Labels

Use these labels on GitHub issues when possible:

- `good first issue`: small, well-scoped, low setup, with files and validation
  called out.
- `help wanted`: useful public task where the approach is clear enough for an
  external contributor.
- `claimed`: someone is actively working on the issue.
- `maintainer-owned`: visible work that should not be duplicated.
- `needs design`: implementation is not ready until the design is agreed.
- `blocked`: waiting on a decision, dependency, or maintainer action.
- Area labels such as `area: docs`, `area: cli`, `area: status`,
  `area: benchmark`, `area: dashboard`, and `area: tests`.

## Maintainer Update Rules

- Keep this board small. If it grows beyond roughly 15 open rows, move older
  or lower-priority work into GitHub issues and keep only the best entry points
  here.
- Every public task should include a scope, expected validation, and owner
  state.
- Do not publish private/local state. Summarize it into a public task only when
  the work is safe for the repository.
- After a meaningful internal milestone, update this board manually if there is
  a new contributor-sized slice.
- Remove or refresh stale tasks instead of leaving obsolete "good first issue"
  entries in place.
