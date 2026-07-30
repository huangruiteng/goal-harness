# What We Learned From LoopX Advisor Mode

LoopX Advisor mode started from a simple hypothesis: use a stronger model to
give bounded advice, then let a cheaper model implement the fix. If the advice
was useful and compact, the cheaper executor could preserve solution quality
while using fewer total tokens.

That hypothesis was worth testing. PR #2406 implemented an opt-in Advisor path
and showed one positive qualification result: both quality arms passed, and
total tokens fell from 263,472 to 130,782, a 50.36% reduction. This proved the
product path could run and that a token reduction was possible on one case.

The broader experiments did not confirm the hypothesis. Token savings appeared
in one isolated qualification, but did not hold across a larger batch. The
Advisor run was often expensive, sometimes timed out, and did not produce a
reliable quality gain. In agent-style coding tasks, Advisor is not a cheap hint;
it is another agent run. Under the current protocol, that extra run does not
pay for itself.

## The Hypothesis

Advisor mode was attractive because it separated thinking from doing. A
stronger model could spend a limited budget identifying the root cause,
important files, invariants, and risks. A cheaper model could then make the
actual edit with less exploration.

If this worked, we expected three signals:

- the combined Advisor plus executor path should use fewer total tokens than
  the quality baseline;
- it should preserve or improve pass rate compared with the cheaper executor;
- the Advisor should produce real rescues, where the cheaper executor fails
  alone but succeeds with advice.

We did not see those signals.

## What We Tested

First, PR #2406 tested the LoopX product path on one provider-backed case. This
was a useful qualification, but it was only one case.

Second, a 20-case batch tested a broader Advisor pattern: Pro Advisor gives
pre-execution advice, then Flash executes. This batch used a TraeX experiment
wrapper rather than the exact LoopX product path, so it should be read as
evidence about the current protocol idea, not as a direct product benchmark.

Third, a smaller ablation and a tuned three-case probe tested whether any
observed effect came from real Advisor insight, generic prompting, or safer
fallback behavior.

## The Main Result: No Reliable Quality Gain

The 20-case result did not show that Advisor helps the weaker executor.

| Arm | Pass count | Result |
| --- | ---: | --- |
| DeepSeek-V4-Flash direct | 11 / 20 | Best observed pass rate |
| DeepSeek-V4-Pro direct | 8 / 20 | Not a stronger baseline in this harness |
| Pro Advisor plus Flash | 10 / 20 | No rescue and one harm |

The key number is rescue count: 0. There was no case where Flash direct failed
and Advisor plus Flash passed. There was also one harm case, where Flash direct
passed but the Advisor combination failed.

Advisor also failed to produce a usable patch in 6 of 20 cases, mostly because
of timeout or missing effective receipts. This matters because a non-effective
Advisor run still spends time and tokens, but does not improve the executor.

## The Token Result: The Extra Agent Run Was Too Expensive

The comparable token subset gives the clearest cost signal.

| Arm | Pass count | Cost proxy |
| --- | ---: | ---: |
| Flash direct | 10 / 13 | About $2.31 |
| Pro direct | 8 / 13 | About $7.35 |
| Pro Advisor plus Flash | 10 / 13 | About $5.13 |

On these 13 cases, Advisor plus Flash matched Flash direct quality at 10 / 13,
but cost about 122% more. It was cheaper than Pro direct, but Pro direct also
passed fewer cases in this harness, so that comparison does not justify a
product claim.

The conclusion is direct: the current Advisor path does not reliably lower
total token usage. The one-case PR qualification showed that savings can happen
in an isolated case. The broader run showed that they do not hold reliably once
Advisor itself is counted as an agent run.

## The Ablation Result: Advisor Did Not Beat A Generic Reminder

The five-case ablation made the conclusion sharper. We replaced the real
Advisor with a fixed generic reminder: identify the root cause, find relevant
files and symbols, form a compact patch plan, consider edge cases, implement
the smallest production-code fix, and verify assumptions against the
repository.

| Arm | Pass count |
| --- | ---: |
| Flash direct | 3 / 5 |
| Fixed generic advice plus Flash | 2 / 5 |
| Existing Pro Advisor plus Flash | 2 / 5 |

The existing Advisor did not beat the generic reminder. On this slice, we
could not prove that the Advisor was adding useful information beyond ordinary
pre-execution prompting.

## The Tuned Probe: Safer, But Still No Rescue

We then tried to make the protocol safer: structure the Advisor output and
fail open when Advisor timed out or returned unusable output.

| Case | Advisor handling | Tokens | Result |
| --- | --- | ---: | --- |
| `astropy__astropy-8707` | High-confidence packet applied | 2,987,804 total | Failed |
| `pydata__xarray-6992` | 300-second timeout; fallback to Flash | 4,437,735 executor | Failed |
| `sympy__sympy-19040` | 300-second timeout; fallback to Flash | 3,358,021 executor | Passed |

The aggregate result was 1 / 3 pass, 0 rescue, and 0 harm. The only pass came
from fallback, not from an applied Advisor packet. Fail-open behavior is useful
as a safety property, but it does not prove that Advisor improves quality or
saves tokens.

## Why This Protocol Did Not Work

The main failure is not that stronger models can never help weaker models. The
failure is that the current Advisor design is a pre-execution suggestion, not a
closed loop.

In the observed Sphinx failure, Advisor identified the important direction:
the current class namespace must take precedence. The executor still wrote a
patch where a base `attr2` could enter the map first, causing the child `attr2`
to be skipped as a duplicate. The target test could pass while an old
regression test still failed. Prior checkpoints with GPT-5.5 and Gemini 3.1
Pro both showed this pattern: Advisor could point in the right direction, but
the final patch could still violate the key invariant.

That is the core protocol gap. Once the executor writes code, the current
Advisor does not review the actual diff. It does not verify that the patch
followed the advice, preserved invariants, or avoided regressions.

Without that loop, Advisor spend often becomes extra analysis cost rather than
a quality or token advantage.

## A Design Learning: Advisor Must Not Become A Second Full Agent

The evidence suggests a more specific failure mechanism. The experimental
Advisor had broad repository access, free exploration, and a free-text handoff.
It repeated much of the executor's expensive work before the executor began.
The combined path therefore paid for two overlapping agent investigations.

More cost-effective multi-model designs give the additional call a narrow,
measurable job. Common examples are issue localization, context compression,
patch review, or verifier-feedback triage. Each can use a bounded input,
structured output, and a small call or token budget. The executor then consumes
an artifact that replaces work it would otherwise repeat.

This is a design hypothesis for the next experiment, not a benchmark result.
The next protocol should trigger at most one limited Advisor call for a defined
purpose:

- before implementation, return a compact evidence packet with relevant files,
  symbols, and invariants;
- after implementation, review only the bounded diff and test summary;
- call a repair round only when the review identifies a specific violation.

The evaluation must separately measure Advisor cost, executor cost, repeated
exploration, rescue count, harm count, and total token use. A future design
earns its complexity only if the bounded call avoids more executor work than it
adds.

## Conclusion: Do Not Merge The Current Advisor Runtime

The current Advisor implementation in PR #2406 should not be merged as product
code.

The evidence shows:

- token savings can appear on a single case;
- broader runs did not show reliable token reduction;
- Advisor plus Flash did not beat Flash direct on pass count;
- rescue count was 0 in the main 20-case batch;
- the ablation did not prove that Advisor adds value beyond a generic reminder;
- tuned fail-open behavior reduced harm but did not create a functional rescue;
- in agent-style coding tasks, the Advisor run itself is too token-expensive
  for the current protocol to improve total token efficiency.
- the next experiment should test narrow, bounded Advisor calls rather than a
  second free-exploration agent.

The right action is to keep this as an experiment report and remove the
Advisor runtime code from PR #2406.

A future attempt should not be another one-shot pre-execution Advisor. It
should be a closed-loop protocol: compact Advisor contract, executor
implementation, Advisor review of the actual diff, and at most one bounded
repair. Until that protocol shows at least one stable rescue with zero harm and
a credible total-token win, Advisor mode should not be presented as a product
optimization.

Source boundary: this article uses public PR metadata, compact experiment
summaries, aggregate case outcomes, and protocol-level observations only. It
does not include raw task text, raw trajectories, raw verifier output, raw
model output, private run paths, credentials, local machine paths, or internal
operating context.
