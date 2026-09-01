# RFC: Benchmark Study Upload and Dashboard Projection v0

| Field | Value |
|---|---|
| Status | Draft integration proposal |
| Date | 2026-09-02 |
| Authors | LoopX maintainers |
| Scope | Provider-neutral benchmark study description, upload records, and read-only dashboard projections |

## 1. Decision

LoopX should let benchmark operators describe a study once, upload compact
public-safe records through an optional provider, and inspect the same facts at
campaign, arm, case, and run granularity.

This proposal does not create another scoring authority:

1. The benchmark-native runner and scorer remain authoritative for outcomes.
2. `benchmark_experiment_board_row_v0` remains authoritative for one run's
   lifecycle, metrics, countability, effort, and insight status.
3. Existing matched-pair and factorial reducers remain authoritative for
   eligible comparisons.
4. A study manifest declares design intent and metric meaning; an upload
   envelope transports allowed records; the dashboard is a derived read model.

The implementation should land in two PRs after this RFC: one for the typed
contract and reducers, then one for a read-only dashboard. Choosing or shipping
a hosted storage provider is outside v0.

## 2. Problem and boundary

The experiment board can answer whether individual runs and comparisons are
countable, but it does not yet carry a compact study-level declaration or a
dashboard-oriented projection. Operators therefore have to reconstruct intended
coverage, arm semantics, denominators, runtime health, and benchmark-specific
metric roles outside the capability.

The v0 surface must be reusable across benchmark families. It must not:

- hard-code a four-arm study, DeepSWE, one model provider, or one sink;
- reinterpret native scores or make non-countable rows formally comparable;
- launch, stop, retry, grade, or mutate benchmark runs;
- upload raw tasks, trajectories, logs, hidden tests, verifier output,
  credentials, or local filesystem paths;
- grant network, runner, scorer, or private-evidence authority;
- turn dashboard state into execution or Todo authority.

## 3. Authority and record model

### 3.1 Study manifest

`benchmark_study_manifest_v0` declares immutable comparison intent:

- `benchmark_id`, `study_id`, `protocol_id`, and case-set identity;
- factor ids, legal levels, arm-to-factor assignments, and baseline arm;
- the primary metric, guardrail and supporting metric catalog;
- intended case and arm coverage;
- comparison protocol and source revisions;
- public-safe labels and optional benchmark extension metadata.

An arm is a set of typed factor assignments, not a special name. For example:

| Arm | `orchestrator` | `domain_hint` |
|---|---|---|
| `goal_plain` | `goal` | `none` |
| `loopx_plain` | `loopx` | `none` |
| `goal_domain_hint` | `goal` | `domain_specific` |
| `loopx_domain_hint` | `loopx` | `domain_specific` |

This representation supports two-arm studies, four-arm factorial studies, and
other declared designs without changing the dashboard schema. Existing
factorial reducers continue to decide whether conditional effects and an
interaction contrast are countable.

### 3.2 Upload envelope

`benchmark_upload_envelope_v0` carries exactly one allowlisted record kind:

- a study manifest;
- an existing experiment-board row;
- a redacted case-insight projection;
- an existing public-safe runtime observation.

The envelope includes producer identity and version, benchmark and study ids,
record kind, stable idempotency key, observation time, source revision, privacy
classification, and payload. The contract validates identity alignment between
the envelope and payload. A provider must return a compact readback receipt
binding the accepted record id, digest, and provider revision.

Retries with the same idempotency key and digest are replays. A corrected
terminal upload is a new envelope that explicitly supersedes the prior
transport record and still obeys the experiment board's legal transition
rules; it must not silently rewrite board authority. The core contract defines
validation and receipts, but neither holds provider credentials nor performs an
external write without a separately activated provider.

### 3.3 Redacted case insight

`benchmark_case_insight_projection_v0` reduces post-run analysis to:

- outcome and failure class;
- compact causal explanation and expectedness;
- benchmark or LoopX implication;
- next probe and confidence;
- public-safe evidence handles or digests.

The projection is not the analyst's raw evidence packet. It cannot contain raw
task text, trajectory excerpts, hidden evaluator material, verifier tails, or
host-local paths.

`benchmark_runtime_observation_v0` is reused unchanged for exact-job authority,
runner liveness, terminal discovery, and runner-invalid classification.
Occupancy and provider-pressure signals come from the existing concurrency
envelope and feedback contracts; retry and timeout facts remain typed run or
provider observations. V0 does not introduce a second schema for any of these
responsibilities.

## 4. Dashboard projection

`benchmark_study_dashboard_v0` is derived from one manifest plus public-safe
records. It has four drill-down levels:

1. **Campaign summary** — intended and completed coverage, score-countable and
   matched denominators, complete factorial cases, in-flight count, primary and
   binary outcomes by arm, paired contrasts, effort, and runtime health.
2. **Arm detail** — protocol and revision, score and success distributions,
   effort distribution, failure taxonomy, and applicable mechanism receipts.
3. **Case matrix** — each arm's metrics, countability, effort, largest eligible
   contrast, and redacted insight for the same case.
4. **Run detail** — lifecycle, metrics, qualification receipts, provenance,
   and public-safe artifact handles.

Every aggregate names its denominator. Formal comparisons include only rows
accepted by the existing matched-pair or factorial contracts. Incomplete
coverage is labelled `provisional`; a larger raw run count must never look like
a stronger matched result.

For ratio metrics, the dashboard may show both case-macro and suite-micro
aggregation when the manifest declares both. For binary outcomes, it should
show success rate and paired `0 -> 1` / `1 -> 0` transitions.

### 4.1 Benchmark-specific metric mapping

Adapters map native metrics into the manifest catalog without changing their
meaning. A software-engineering benchmark may declare:

| Role | Example metric | Dashboard use |
|---|---|---|
| Primary | feature or requirement pass ratio | Main partial outcome |
| Guardrail | preservation or regression pass ratio | Existing behavior safety |
| Guardrail | binary reward | End-to-end success rate and transitions |
| Supporting | duration, steps, turns, tokens, estimated cost | Effort and efficiency |

Partial progress must not replace the feature, preservation, or binary outcome.
Other benchmark families keep their own native metric names, units, directions,
and success thresholds.

For example, a DeepSWE adapter can map feature/F2P into the primary partial
outcome, preservation/P2P and reward into guardrails, and duration, steps,
turns, tokens, and estimated cost into supporting effort metrics. That mapping
is adapter metadata in the manifest, not a DeepSWE field in the core schema.

## 5. Privacy and provider boundary

The upload allowlist contains compact metrics, typed qualification reason codes,
redacted insights, digests, and provider-scoped artifact handles. Raw task text,
raw trajectories, logs, hidden tests, verifier output, credentials, auth files,
Docker sockets, and local paths remain outside the contract.

Typed record kinds and schemas enforce this boundary. The implementation should
not rely on a substring denylist to decide whether arbitrary prose is safe.
Record producers own redaction before envelope construction, and a provider may
apply stricter policy without weakening the core boundary.

An optional provider owns authentication, transport, retention, and remote
readback. Installing the benchmark capability or rendering a dashboard grants
none of those permissions.

## 6. Delivery slices

### PR 1: Contract and reducers

- add the study manifest, upload envelope/readback receipt, and redacted insight
  projection schemas;
- reuse experiment-board, factorial, and runtime-observation contracts;
- derive a provider-neutral dashboard data packet without rendering UI;
- expose preview/validation CLI entry points, with no implicit network write;
- add semantic tests for identity alignment, idempotent replay, supersession,
  denominator disclosure, incomplete coverage, and private-boundary rejection.

### PR 2: Read-only dashboard

- render the campaign, arm, case, and run views from the derived packet;
- preserve countability and provisional labels in every view;
- provide local readback and focused rendering/accessibility validation;
- complete the repository's first-screen preview gate before finalizing the
  dashboard presentation.

A concrete remote provider should be proposed only when a real sink supplies
an authentication, privacy, transport, and readback lifecycle to validate.

## 7. Acceptance criteria

The v0 direction is accepted when:

- one manifest can represent both a simple baseline/treatment study and a
  factorized four-arm study;
- existing experiment-board rows round-trip through an envelope without losing
  metric, countability, effort, fidelity, or provenance meaning;
- reducers expose campaign, arm, case, and run projections with explicit
  denominators and no new scoring decisions;
- the dashboard renders benchmark-native partial, binary, guardrail, effort,
  and runtime-health data without benchmark-specific core fields;
- invalid identity, unknown record kind, silent terminal rewrite, and forbidden
  evidence references fail closed;
- all external transport remains optional, provider-owned, and independently
  authorized.
