# Benchmark Toolkit

`benchmark-toolkit` is LoopX's built-in, provider-neutral surface for permission,
artifact, integrity, and reusable agent-runtime boundaries around benchmark
experiments. It does not own benchmark-family runners, result ledgers, or scoring
adapters.

## Native Codex Goal runtime

Benchmark adapters that use the Codex app-server Goal API should import
`loopx.capabilities.benchmark_toolkit.native_codex_goal`. The module provides the
real stdio JSON-RPC process transport, the ordered Goal transaction, terminal event
correlation, Goal-status polling across automatic continuation turns, and a
public-safe receipt. A runner supplies its own isolated process command,
environment, sandbox policy, task bridge, and timeout; it should not copy the
Goal state machine.

The runnable source example is
[`benchmark/deepswe/run_native_codex_goal.py`](../../../benchmark/deepswe/run_native_codex_goal.py).
Its `--preflight-only` mode proves a live Codex initialize/thread/Goal attachment
without invoking a model. Full mode starts one turn and waits for a correlated
terminal event, then keeps draining Codex-owned continuation turns until the Goal
leaves `active`. The same total timeout covers the full Goal lifecycle.

### Formal installed profile and skill discovery

A treatment that only supplies a Goal prompt and a source-checkout CLI has not
proved the real LoopX product path. The prompt, installed skills, and installed
CLI are three independent inputs. Use `native_codex_profile` to create an isolated
local release through LoopX's shipped `scripts/install-local.sh` instead of copying
skill files or importing an arbitrary checkout:

```python
from loopx.capabilities.benchmark_toolkit.native_codex_goal import NativeGoalConfig
from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    install_native_codex_profile,
    native_codex_profile_environment,
    render_native_codex_goal_prompt,
)

profile = install_native_codex_profile(loopx_source, isolated_profile_root)
prompt = render_native_codex_goal_prompt(
    profile,
    project_root=task_visible_cwd,
    goal_id=goal_id,
    agent_id=agent_id,
    runtime_registry_path=case_runtime_registry,
)
config = NativeGoalConfig(
    cwd=task_visible_cwd,
    objective=prompt.task_body,
    task_instruction=task_instruction,
    required_skill_ids=profile.required_skill_ids,
)
process_env = native_codex_profile_environment(profile)
```

The profile installer redirects the release, executable, manual, home, and Codex
skill roots into the supplied isolated directory. It uses the fixed installer path,
including its generated `$loopx` entry skill and packaged workflow-skill readback;
unrelated interactive slash-command surfaces are disabled for this non-interactive
worker. Inspection verifies a release-snapshot CLI, exact source revision, clean
source by default, skill-tree digests, and `doctor --agent-type codex-app-ssh`.

`render_native_codex_goal_prompt` calls `heartbeat-prompt --thin` through the
release-snapshot CLI, requires the `codex_app_ssh_goal` profile and interface budget,
and proves that the returned body names that installed CLI. For an isolated case it
also replaces the generic global-registry token with the explicit case registry.
Use `native_codex_profile_environment` for app-server so the same profile supplies
`HOME`, `CODEX_HOME`, and `PATH`. Setting `required_skill_ids` makes the native
runtime call the real app-server `skills/list` surface before `thread/start`;
missing skills, discovery errors, or a wrong cwd fail before any model turn. The
path-free profile, prompt, and Goal receipts can then prove all three inputs without
publishing installation paths, prompt text, or skill bodies.

Run the formal installer plus no-model readback smoke with:

```bash
python examples/benchmark-native-goal-installed-profile-smoke.py \
  --require-app-server
```

The helper installs only into its target directory. It grants no credential,
network, task, evaluator, upload, submission, or scoring authority; those remain
runner-owned boundaries.

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
6. Reduce the official result through the benchmark-owned scoring path.
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
```

All commands are local and no-upload by default. `benchmark-toolkit` grants no model,
Docker, runner, upload, submission, publication, or production authority.

The active benchmark research program and current public-safe practice live under
[`benchmark/`](https://github.com/huangruiteng/loopx/blob/main/benchmark/README.md). Historical runners and dated research
packets are retained under [`deprecate/benchmark-legacy/`](https://github.com/huangruiteng/loopx/blob/main/deprecate/benchmark-legacy/README.md)
for source archaeology only.
