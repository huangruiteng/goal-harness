# Benchmark Toolkit

`benchmark-toolkit` is LoopX's built-in, provider-neutral surface for preparing,
qualifying, comparing, and recording agent benchmark experiments. It composes
existing `loopx benchmark` commands with a fail-closed integrity gate; benchmark-
family launch details remain in `loopx/benchmark_adapters/`.

The toolkit borrows the useful contracts already established by modern benchmark
runners: an ATIF-compatible agent trajectory, a separately owned verifier phase,
explicit attempt accounting, and compact result reduction. LoopX adds the control-
plane pieces that a container runner cannot infer by itself: model-visible source
permissions, host and cross-trial isolation, credential propagation, canonical
case-local state, verifier ordering, public/private evidence reduction, and matched-
pair countability.

## Integrity qualification

Run integrity qualification after the agent phase and after the runner has produced
its isolation attestation. The trajectory and any sensitive values remain private
local inputs:

```bash
export BENCHMARK_PROVIDER_CANARY='a-private-value-known-to-the-controller'

loopx benchmark integrity-qualification \
  --trajectory-json .local/private-run/agent/trajectory.json \
  --runtime-attestation-json .local/private-run/runtime-attestation.json \
  --sensitive-value-env BENCHMARK_PROVIDER_CANARY \
  --require-qualified \
  --format json
```

The command emits `benchmark_integrity_qualification_v0`. It records only stable
labels, counts, reason codes, step ids, and SHA-256 digests. It never emits raw tool
arguments, observations, sensitive values, input paths, task text, verifier output,
or trajectory content. Invalid private input returns a generic fail-closed error so
JSON parser details cannot echo private data.

Qualification rejects a run when it detects any of the following:

- answer, hidden-test, verifier, other-trial, or controller-private source access;
- host escape, credential probing or exposure, or shell network access;
- malformed or incomplete ATIF tool evidence;
- missing runner authority or any required runtime isolation attestation.

`benchmark_cheating_detected` is narrower than `integrity_qualified=false`.
Restricted evaluation or cross-trial access is classified as cheating. Missing
isolation proof or a credential leak still makes the run uncountable, but LoopX does
not relabel that absence of proof as confirmed answer cheating.

## Runner attestation

The attestation is a compact runner-owned JSON object, not an agent assertion:

```json
{
  "schema_version": "benchmark_runtime_integrity_attestation_v0",
  "authority": "runner",
  "benchmark_id": "fixture@v0",
  "case_id": "case-1",
  "agent_phase_isolated": true,
  "evaluator_sources_denied": true,
  "other_trials_denied": true,
  "controller_state_denied": true,
  "host_escape_denied": true,
  "shell_network_denied": true,
  "provider_credential_shell_excluded": true,
  "case_local_control_state": true,
  "canonical_control_state_root": true,
  "independent_verifier": true,
  "verifier_started_after_agent": true,
  "official_feedback_blinded": true
}
```

Every boolean is required and must be true. A clean trajectory scan cannot prove a
filesystem or namespace permission boundary, so missing attestation fails closed.
Likewise, the attestation alone cannot prove what tool calls actually occurred; both
evidence channels are required.

`benchmark_id`, `case_id`, and a custom policy's `policy_id` are public labels, not
paths. Path-like values fail closed and are emitted only as `redacted`, so a runner
cannot move an operator directory into the public receipt through identifier fields.

Benchmark-specific private roots can be added without committing them through an
ignored `benchmark_integrity_policy_v0` file:

```json
{
  "schema_version": "benchmark_integrity_policy_v0",
  "policy_id": "local-run-policy",
  "denied_argument_markers": {
    "other_trial_request": ["<private-other-trial-root>"],
    "controller_private_state_request": ["<private-controller-root>"]
  }
}
```

The policy values are used only for in-memory matching and are not copied into the
receipt.

## Experiment lifecycle

A countable experiment uses the toolkit in this order:

1. Declare a `run_permission_policy_v0` and preflight the runner boundary.
2. Launch one frozen case/arm; do not expose evaluator sources or official feedback.
3. Capture ATIF tool evidence and a runner-owned runtime attestation.
4. Run `integrity-qualification`; stop on any blocker.
5. Run the independent verifier only after the agent phase.
6. Reduce the official result into compact `benchmark_run_v0` / result evidence.
7. Apply attempt-countability, treatment-fidelity, and matched-pair gates before any
   comparison claim or ledger update.

Integrity qualification is necessary but not sufficient for a score claim. It does
not establish task correctness, official score authority, experiment parity, or a
LoopX advantage. `score_claim_eligible=true` only permits the official score and
matched-pair gates to run; `score_claim_countable` and `matched_pair_countable` stay
false in this receipt. Those remain separate verifier and comparison contracts.

## Related commands

```bash
loopx benchmark classify-artifacts <paths...> --format json
loopx benchmark candidate-source-boundary <paths...> --require-clean --format json
loopx benchmark run <family> --goal-id <goal-id> --format json
loopx benchmark run-ledger-check --goal-id <goal-id> --format json
```

All commands are local and no-upload by default. `benchmark-toolkit` grants no model,
Docker, runner, upload, submission, publication, or production authority.
