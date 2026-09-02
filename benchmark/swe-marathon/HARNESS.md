# SWE-Marathon: codex × LoopX evaluation harness

This directory contains the agent adapters, scoring scripts, and skills used to run
a five-mode comparison of `codex` and LoopX on **SWE-Marathon** (Harbor).

📊 Results, interactive visualization, and per-trial trajectory browser:
**https://bouwenzhou.github.io/loopx/** (see also the summary in `README.md`).

## The five modes

| mode | role | what it is |
|---|---|---|
| `plain` | baseline① | bare codex, objective fixed to `"Finish the task."` |
| `goal` | baseline② | **codex-native goal** (codex's own goal feature) — not LoopX |
| `ssh-goal` | LoopX① | codex-native goal + LoopX-rendered goal body / skills, ssh-driven |
| `codex-cli` | LoopX② | in-container `loopx` CLI renders the goal body (carries claim/lease/peer boilerplate) |
| `heartbeat` | LoopX③ | heartbeat-driven continuation / unblock + LoopX goal body / skills |

`plain`→`goal` isolates codex-native goal; `goal`→{ssh-goal, codex-cli, heartbeat}
isolates LoopX's increment on top of codex-native goal.

## Layout

```
agents/                     # Harbor agent adapters (the treatment definition)
  codex_loopx_agent.py      #   LoopX treatment: codex-native goal + LoopX skills/CLI/goal-body
  codex_goal_agent.py       #   codex-native goal baseline
  native_codex_goal.py      #   codex-native goal turn driver (harness-vendored)
  codex_offline.py          #   offline/model-only codex runner
scoring/                    # reporting — reward is binary; partial_score is the main signal
  _compare.py               #   five-mode comparison table
  _partial.py               #   continuous-score (partial_score / test pass-rate) table
  _summarize.py             #   per-mode roll-up
  _aggregate.py             #   aggregate all trials to a single data.json (feeds the web viz)
  _extract_traj.py          #   extract per-trial trajectories from codex rollouts
  _build_viz.py             #   build the self-contained results web page
skills/                     # the two five-mode benchmark skills (SWE-Marathon, Terminal-Bench 4)
```

The adapters build on `loopx.capabilities.benchmark_toolkit` and `harbor`. The full run
orchestration (docker/network/model-gateway wiring) lives in the evaluation harness and
is environment-specific; it is intentionally **not** included here (it depends on internal
network topology). These adapters + scoring scripts are the reusable, portable core.

## Scoring conventions (read before interpreting numbers)

- Harbor `reward` is **binary** and mostly 0 under a compressed budget — low signal.
- Prefer the task-authored **continuous** score `partial_score` (in
  `/logs/verifier/metrics.json`); `_partial.py` also computes a raw test pass-rate.
- **Build failures** (Rust-family tasks) zero out `partial_score` at a gate; they are
  flagged (✗) and **excluded from the reward/partial means** — that is an
  environment/gate issue, not a capability signal.
- Per-mode means are computed only over tasks that **all five modes** ran.

These conventions are load-bearing and documented inline in each script (they encode bugs
that were hit and fixed — e.g. mode-name normalization, job-vs-trial `result.json`,
half-written `metrics.json` from re-running trials).

## Reproduce the report from a results tree

```bash
python3 scoring/_aggregate.py    <out_dir> viz/data.json          # aggregate trials
python3 scoring/_extract_traj.py <out_dir> viz/trajectories       # extract trajectories
python3 scoring/_build_viz.py    viz/data.json viz/SUMMARY.md viz/index.html
python3 scoring/_compare.py      <out_dir>                        # terminal comparison table
```

## Headline finding

Most of the improvement over bare codex (self-completion 0→12/15, partial 0.710→0.767)
comes from codex's **native goal** feature. The three LoopX modes add only marginal gains
on top of codex-native goal (partial +0.006 / +0.011 / −0.065) at 30–56% higher cost;
binary reward moves only for `heartbeat`. A usage-integrity check (in `README.md`)
separates harness-level LoopX (goal injection + continuation, present in all three LoopX
modes) from agent-level `loopx` CLI calls (sparse: 1–4 of 15 trials).
