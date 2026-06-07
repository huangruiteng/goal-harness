# Paper And Runner Dossier

Checked at: 2026-06-07T17:48:00+08:00.

This dossier ranks candidate long-horizon agent benchmarks for Goal Harness
research. It is a research artifact, not a product implementation plan. Any
Goal Harness feature discovered here should be split into normal product code,
examples, or contract docs outside this topic folder.

## Current Recommendation

Use Terminal-Bench 2.0 as the first official-runner probe, then SWE-Marathon as
the first heavy long-horizon software-engineering probe.

The reason is pragmatic. Terminal-Bench has an open runner, Docker-style
terminal tasks, verified leaderboard entries, and visible Codex/Codex-adjacent
agent rows. It is the fastest way to test whether a passive Goal Harness wrapper
can add restartability, state truth, event ledgers, and failure attribution
without changing the official scoring protocol.

SWE-Marathon is closer to the user's paper-level ambition because the tasks are
explicitly ultra-long software-engineering work, but it is heavier: the public
repo uses a Harbor fork, task execution is likely expensive, and some log
access is gated by external credentials. It should be the second lane after the
Terminal-Bench wrapper boundary is understood.

## Ranking

| Rank | Candidate | Use | Why |
| --- | --- | --- | --- |
| 1 | Terminal-Bench 2.0 | First official-runner probe | Open benchmark repo, terminal task model, verified leaderboard, visible Codex entries, and a protocol that already treats agent tools as part of the scored system. |
| 2 | SWE-Marathon | First heavy SWE probe | Strongest fit for hours-to-days software-engineering work; public repo and 20 ultra-long tasks, but setup and cost are heavier. |
| 3 | LongCLI-Bench | Paper hypothesis and failure-analysis source | Directly studies long-horizon CLI programming, step-level failures, and human-agent collaboration gains; runner openness still needs verification before it becomes an execution lane. |
| 4 | WildClawBench | Native-runtime comparison lane | Promising because it evaluates real CLI harnesses including Codex-style harnesses in reproducible containers, but it is very new and needs protocol/code review. |
| 5 | HORIZON / METR-style signals | Diagnostic and positioning signal | Useful to explain long-horizon degradation and compare across domains, but currently better as a leaderboard/diagnostic reference than as the first runnable Goal Harness integration. |
| 6 | SWE-EVO / RoadmapBench / LongDS-Bench | Watchlist | Useful for breadth and paper framing after one official runner works. |
| 7 | Tau-style suites | Simulator research only | Valuable for user-simulator design, but not the headline long-horizon engineering benchmark. |

## Source Notes

### Terminal-Bench 2.0

Evidence:

- Official Epoch page describes a task as an instruction, Docker environment,
  and test script, and says models are paired with agent tools such as Claude
  Code, OpenAI Codex CLI, Terminus, and Goose.
- Terminal-Bench paper presents 89 hard terminal-environment tasks with
  verification tests and reports frontier models and agents below 65 percent.
- Official leaderboard page for `terminal-bench@2.0` shows verified GPT-5.3
  Codex rows including Simple Codex and Terminus 2.
- GitHub repo describes Terminal-Bench as evaluating real-world end-to-end
  terminal tasks autonomously.

Fit for Goal Harness:

- Strong first target for passive Goal Harness because the benchmark already
  separates agent tool/scaffold from model.
- Goal Harness can wrap around run setup, event ledger, restart state,
  validation evidence, and failure attribution while preserving official task
  scoring.
- The benchmark explicitly forbids timeout/resource modification in leaderboard
  submissions, so Goal Harness integration must avoid changing resource budget
  or task files.

Open questions:

- Determine whether a passive wrapper can be submitted as a custom agent or
  must be used only for local A/B studies.
- Check whether Harbor's custom-agent path can launch Codex CLI directly or
  needs a small adapter.

Sources:

- https://epoch.ai/benchmarks/terminal-bench/
- https://arxiv.org/abs/2601.11868
- https://www.tbench.ai/leaderboard/terminal-bench/2.0
- https://github.com/harbor-framework/terminal-bench

### SWE-Marathon

Evidence:

- Public repo asks whether agents can complete ultra-long-horizon software
  work.
- Repo uses a Harbor fork, includes tasks, rubrics, scripts, and Apache 2.0
  licensing.
- Hugging Face dataset page says there are 20 ultra-long software-engineering
  tasks, each with a containerized environment, precise instruction,
  comprehensive tests, and an oracle/reference solution.
- Dataset page says tasks are intended for evaluating agents on realistic
  long-horizon hours-to-days software-engineering tasks end-to-end in a
  sandboxed environment.

Fit for Goal Harness:

- Strongest research target once Terminal-Bench wrapper mechanics are known.
- Directly tests multi-hour/multi-day continuation, state handoff, validation
  discipline, and restartability.
- Likely a good paper target because Goal Harness's thesis is about reducing
  coordination load and preserving durable state over long projects.

Risks:

- Higher cost and wall-clock time.
- Public repo's sample command shows Claude Code; Codex CLI compatibility needs
  runner inspection before making claims.
- Some trajectory-log access requires external credentials, so early work
  should use public task files and local dry-runs only.

Sources:

- https://github.com/abundant-ai/swe-marathon
- https://www.swe-marathon.org/
- https://huggingface.co/datasets/rdesai2/swe-marathon

### LongCLI-Bench

Evidence:

- ArXiv paper introduces 20 long-horizon CLI programming tasks from computer
  science assignments and real-world workflows.
- It covers from-scratch implementation, feature addition, bug fixing, and
  refactoring.
- It reports state-of-the-art pass rates below 20 percent, with many tasks
  stalling before 30 percent completion.
- It finds human-agent collaboration through plan injection and interactive
  guidance improves outcomes, which aligns with Goal Harness's supervised
  long-horizon thesis.

Fit for Goal Harness:

- Excellent source for paper framing and failure taxonomy.
- Useful for designing operator-simulator experiments because it explicitly
  discusses collaborative guidance.

Risk:

- Runner/code availability and Codex CLI baseline need verification before it
  becomes an execution target.

Source:

- https://arxiv.org/abs/2602.14337

### WildClawBench

Evidence:

- ArXiv paper frames the gap as existing benchmarks being too synthetic,
  short-horizon, mock-service based, or final-answer oriented.
- It contains 60 human-authored tasks with roughly 8 minutes average wall time
  and more than 20 tool calls.
- It runs in reproducible Docker containers hosting actual CLI harnesses such
  as OpenClaw, Claude Code, Codex, or Hermes Agent.
- It reports harness choice alone can shift one model by up to 18 points.

Fit for Goal Harness:

- Useful after Terminal-Bench because it emphasizes native runtime and harness
  effects, which is exactly where Goal Harness should claim value.

Risk:

- Very new; code, scoring, and leaderboard stability need review before a
  serious run.

Source:

- https://arxiv.org/abs/2605.10912

### HORIZON / METR-style Signals

Evidence:

- HORIZON paper studies long-horizon failure behavior across domains and uses
  trajectory-grounded failure attribution.
- HORIZON site presents itself as a live ranking for frontier models and agents
  on long-horizon software engineering, with METR-Horizon as the primary signal
  and Terminal-Bench plus SWE-style benchmarks as secondary signals.

Fit for Goal Harness:

- Use as a positioning and diagnostic source, not first runner.
- The failure-attribution angle is useful for Goal Harness result reports.

Sources:

- https://arxiv.org/abs/2604.11978
- https://horizonbench.org/

### LongDS-Bench

Evidence:

- ArXiv paper introduces long-horizon, multi-turn data analysis tasks requiring
  agents to maintain, update, restore, and compose evolving analytical states.
- It reports performance degradation over late turns and argues the bottleneck
  is maintaining correct analytical state rather than merely increasing steps.

Fit for Goal Harness:

- Watchlist for state-truth research after engineering benchmark lanes run.
- Relevant to Goal Harness because it isolates state maintenance failures.

Source:

- https://arxiv.org/abs/2605.30434

## First Execution Slice

The next bounded implementation/research slice should be:

1. Inspect Terminal-Bench's Harbor runner and custom-agent path.
2. Determine whether Codex CLI can run as an official custom agent, or whether
   Goal Harness must run a local-only passive A/B wrapper first.
3. Write a `terminal_bench_probe_v0` note with:
   - command attempted or dry-run command;
   - runner version/source;
   - resource/scoring boundary;
   - allowed passive logging surface;
   - whether official leaderboard submission remains valid;
   - next stop condition.

Do not start SWE-Marathon until the Terminal-Bench wrapper boundary is known.
