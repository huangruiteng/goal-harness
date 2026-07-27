# Planner Worker Delivery Eval V0

Checked at: 2026-07-27.

This note records a local delivery evaluation for LoopX planner-worker mode. It
is public-safe by design: it reports compact counters, model routes, validation
commands, and claim boundaries only. It does not include raw agent transcripts,
private benchmark traces, verifier output, credentials, local machine paths, or
hidden task material.

## Experiment Identity

- report_id: `planner-worker-delivery-eval-v0`
- mode_under_test: `planner_worker`
- baseline_route: `GPT-5.5` direct delivery
- treatment_route: `GPT-5.5` planner plus `DeepSeek-V4-Flash` worker
- task_slice: five local Python bug-fix delivery fixtures
- validation_surface: standard-library `unittest`
- leaderboard_evidence: `false`
- official_benchmark_evidence: `false`

The goal was not to estimate official benchmark score. The goal was to test
whether the planner-worker contract can preserve delivery while reducing model
cost on small, focused implementation tasks.

## Contract Under Test

The planner must return a parseable `planner_worker_plan_v0` JSON object. It
must not rely on prose, Markdown fences, raw transcripts, or fallback parsing.

Each executable step carries the worker execution policy:

| Field | Purpose |
| --- | --- |
| `recommended_executor` | Selects `cheap_worker`, `strong_worker`, or `planner_only`. |
| `worker_model_tier` | Records the intended cost tier. |
| `worker_autonomy` | Allows `narrow`, `bounded`, or `open` worker freedom. |
| `context_budget` | Caps target-file context and extra-file access. |
| `validation_commands` | Lists the commands the worker should run before declaring done. |
| `done_criteria` | Defines delivery completion in testable terms. |
| `escalation_policy` | Says when a cheap worker should stop and ask for stronger help or more context. |

The worker receives the normalized step prompt and is expected to execute the
plan step, validate the result, and avoid broad re-planning unless the planner
explicitly grants that freedom.

## Evaluation Design

For each case, two independent copies of the same fixture were used:

1. Baseline: `GPT-5.5` directly edited the task files and ran the validation.
2. Treatment: `GPT-5.5` produced a strict JSON planner-worker plan, then
   `DeepSeek-V4-Flash` executed the first worker step and ran the same
   validation.

The treatment was counted only when all of these held:

- the planner JSON parsed successfully;
- the worker completed a patch;
- the same `python -m unittest ...` command passed;
- the result did not require fallback plan injection.

Costs use the local estimate:

| Model | Input / 1k | Output / 1k |
| --- | ---: | ---: |
| `GPT-5.5` | `0.02` | `0.08` |
| `DeepSeek-V4-Flash` | `0.0005` | `0.002` |

Cached input tokens were reported by TraeX but were not priced separately in
this note because the repository does not define a public cached-token price
schedule for these model routes.

## Results

Summary:

| Metric | Baseline | Planner Worker |
| --- | ---: | ---: |
| Cases | `5` | `5` |
| Delivery pass count | `5` | `5` |
| Planner JSON parse count | n/a | `5` |
| Total estimated cost | `9.168240` | `5.605126` |
| Estimated cost delta | n/a | `-3.563114` |
| Estimated savings ratio | n/a | `38.86%` |

Case-level results:

| Case | Validation | Baseline Cost | Planner Worker Cost | Delta | Delivery |
| --- | --- | ---: | ---: | ---: | --- |
| `parser_bracket_prefix` | `python -m unittest test_parser.py` | `1.848300` | `1.206431` | `-0.641869` | both passed |
| `calculator_unary_minus` | `python -m unittest test_calculator.py` | `1.841680` | `0.822904` | `-1.018776` | both passed |
| `config_deep_merge` | `python -m unittest test_config_merge.py` | `1.832280` | `1.195793` | `-0.636487` | both passed |
| `slugify_collapse_dashes` | `python -m unittest test_slug.py` | `1.823580` | `1.191474` | `-0.632106` | both passed |
| `range_parser_open_ended` | `python -m unittest test_range_parser.py` | `1.822400` | `1.188524` | `-0.633876` | both passed |

## Interpretation

The strict planner-worker contract held for this local delivery slice:

- `GPT-5.5` produced parseable planner-worker JSON on all five cases.
- `DeepSeek-V4-Flash` completed all five worker deliveries.
- The same standard-library validation commands passed in both arms.
- The treatment route reduced estimated cost by `38.86%` while preserving
  delivery on these focused tasks.

The result supports the planner-worker hypothesis for scoped implementation
work: a stronger planner can convert task understanding into a bounded worker
contract, then a cheaper worker can complete the patch and validation.

## Claim Boundary

This report may claim:

- local delivery parity on five small Python bug-fix fixtures;
- successful strict JSON planner parsing on five of five treatment cases;
- estimated cost reduction under the stated local pricing assumptions;
- evidence that cost-aware worker routing can be useful when the planner
  produces concrete target files, validation commands, and escalation policy.

This report must not claim:

- official benchmark improvement;
- leaderboard eligibility;
- broad performance across large or hidden tasks;
- that cached-token pricing would preserve the exact same savings ratio;
- that every task should use a cheap worker.

The planner contract still needs real benchmark and larger-case evaluation.
Large ambiguous tasks may need `strong_worker` or `planner_only` decisions
instead of `cheap_worker`.

## Negative Results And Risks

Earlier local read-only probes showed that planner-worker can become more
expensive when the planner or worker receives uncontrolled repository context.
That is why this contract now requires:

- strict planner JSON;
- explicit executor selection;
- context budget;
- validation commands;
- done criteria;
- escalation policy.

The main remaining risk is context assembly. If a runtime injects large
irrelevant context into either planner or worker turns, the cost benefit can
disappear even when the model route is cheaper.

## Next Decision

Continue, but only with delivery-gated comparisons.

Minimum next evidence:

- run the same strict contract on a medium case with multiple dependent worker
  steps;
- record whether the planner selects any `strong_worker` or `planner_only`
  steps;
- compare cost only when both baseline and treatment pass identical validation;
- keep raw transcripts and local run artifacts out of public docs.
