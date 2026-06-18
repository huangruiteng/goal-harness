# Benchmark Split-Control Remote Executor V0

Status: design contract + smoke-tested public gate.

This contract defines the benchmark route used when Codex and Goal Harness stay
on the local trusted machine while a remote development host provides Docker,
runner dependencies, task-data staging, bounded command execution, and compact
result reduction.

## Boundary

Local agent owns:

- Codex CLI and Codex auth;
- Goal Harness state, quota, todo projection, and writeback;
- model invocation, planning, and patch generation;
- public/private filtering before any artifact becomes durable.

Remote executor owns:

- Docker/container runtime;
- benchmark runner dependencies;
- task-data or image staging;
- bounded command/file execution requested by the local agent;
- compact result reduction that does not expose raw task text, trajectories,
  verifier logs, credentials, uploads, or submit paths.

The remote host must not be treated as an agent-auth environment. Missing
remote `codex`, `codex-acp`, or model credentials is a diagnostic fact, not a
cross-benchmark blocker. A benchmark is blocked only by one of the actual
split-control gates:

- local agent not ready;
- remote executor base missing;
- split-control adapter missing;
- remote runner tooling missing;
- task data or image missing;
- remote node runtime missing only when a specific runner declares that it
  requires remote Node/npm.

## Current Use

The same route applies to the three active benchmark families:

- Terminal-Bench: local Codex/Goal Harness drives the attempt; the remote side
  supplies Docker, Harbor or a runner wrapper, and compact result ingestion.
- SkillsBench: local Codex/Goal Harness drives the attempt; the runner must no
  longer assume Codex ACP starts inside the remote worker before a
  split-control adapter exists.
- Agents' Last Exam: local Codex/Goal Harness and local auth remain trusted;
  the remote side handles Docker, source/task-data staging, CUA/provider
  capacity where applicable, and compact result reduction.

## Validation

Run:

```bash
python3 examples/benchmark-split-control-remote-executor-smoke.py
```

The smoke asserts that missing remote Codex/Codex-ACP is non-blocking, while
adapter, runner-tooling, and task-data blockers remain explicit.
