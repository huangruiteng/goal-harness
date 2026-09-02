# SWE-Marathon runtime: mode framework + automation driver

The **automation-driven continuation loop** used by the codex×LoopX comparison. This is
what makes the `heartbeat` mode the most robust of the LoopX modes: an external driver
owns the wakeups, so turn boundaries are guaranteed by the driver instead of by a human
(codex-cli TUI) or by Codex's own visible-Goal loop (ssh-goal).

## Why automation-driven is the stable path

In the eval, `heartbeat` solved tasks that `codex-cli` churned on. Root cause: the
`codex_cli` profile omits `--begin-turn` (it assumes a human starts each turn in the TUI),
so run **unattended** its continuation loop degenerates — the agent is re-woken but does
almost no real work (e.g. 11 wakeups / 13 tool calls, ends `blocked`). The automation
driver here supplies clean turn boundaries itself (`--turn-instance-id` per turn +
`quota should-run` guard), so every wakeup does real work.

## Layout

```
runtime/
  modes/
    profiles.py          # declarative Mode table: ssh-goal / codex-cli / heartbeat
                         #   (runtime_profile, host_surface, continuation owner, guard flags)
    run_mode.py          # CLI entry: pick a mode, install profile, run a session
    session.py           # session lifecycle over the mode
    codex_host.py        # host wiring
    profile_install.py   # installs the loopx runtime profile / skills into CODEX_HOME
  turn/
    loopx_turn_runner.py # THE automation driver: per-turn loop with --turn-instance-id,
                         #   quota should-run guard, turn timeout, HEAD-moved progress check
    loopx_native_codex.py# native-codex turn driver
    goal_codex.py        # visible-Goal turn driver (ssh-goal / codex-cli)
    codex_nosandbox_wrapper.py
```

## The three modes (from `modes/profiles.py`)

| mode | runtime_profile | continuation owner | notes |
|---|---|---|---|
| `ssh-goal` | `codex_app_ssh_goal` | Codex (visible Goal) | guard carries `--begin-turn`; native unattended path |
| `codex-cli` | `codex_cli` | Codex (visible Goal) | guard has **no** `--begin-turn` (human-attended TUI by design) |
| `heartbeat` | `generic_cli` | **driver** (this runtime) | driver owns wakeups via `--turn-instance-id`; **most robust unattended** |

## Dependencies

- `loopx.capabilities.benchmark_toolkit` (native_codex_goal / native_codex_profile) — upstream.
- The trial/agent framework (`harbor` / `pier`) providing the environment + installed Codex agent.
- Knobs via env, e.g. `MR_LOOPX_TURN_TIMEOUT` (per-turn timeout seconds, default 1200).

No internal network topology or credentials are embedded; environment-specific wiring
(gateways, proxies) lives outside this runtime and is supplied via env.
