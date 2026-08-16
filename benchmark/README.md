# Benchmark research workspace

This is LoopX's active, non-package workspace for benchmark practice and narrow
runner experiments. Its authority is the
[Long-Horizon Harness Benchmark and Research Program v0](../docs/architecture/rfcs/long-horizon-harness-benchmark-research-program-v0.md).

The workspace follows three rules:

1. benchmark-native task, runner, verifier, and score semantics remain
   authoritative;
2. current real-run practice outranks legacy LoopX benchmark abstractions;
3. only generalized code and public-safe conclusions enter this directory.

Reusable product policy stays in
[`benchmark-toolkit`](../docs/capabilities/benchmark-toolkit/README.md). The
toolkit owns provider-neutral permission, artifact, and integrity boundaries.
This directory may contain small research seams and practice notes, but it is
not installed as a second LoopX Python package and does not grant execution or
publication authority.

## Current work

- [`deepswe/README.md`](deepswe/README.md) records the current public-safe
  DeepSWE method: frozen selection, matched-arm authority, native Goal proof,
  independent verification, invalid-run replacement, and compact evidence.
- [`native_codex_goal.py`](native_codex_goal.py) is the minimal transport-neutral
  transaction used to attach an active Goal to a Codex app-server thread and
  start one task turn. It deliberately does not own process supervision,
  environment bridging, verifier execution, or benchmark scoring.

Legacy runners and dated packets are archived under
[`deprecate/benchmark-legacy/`](../deprecate/benchmark-legacy/README.md). They are
candidate evidence only, not the architecture for new work.
