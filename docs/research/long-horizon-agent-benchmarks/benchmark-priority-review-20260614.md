# Benchmark Priority Review 2026-06-14

This review re-ranks benchmark lanes by the corrected baseline definition:
Codex CLI goal mode versus a Goal Harness assisted Codex worker. It uses only
public-safe compact run ledger entries and public leaderboard/source evidence;
it does not rely on raw task text, hidden tests, private trajectories, Docker
logs, credentials, uploads, or public leaderboard submissions.

## Baseline Evidence Classes

Use three separate evidence classes when ranking benchmark lanes:

1. `direct_codex_goal_mode_low`: a direct Codex CLI or Codex goal-mode baseline
   is already low enough to leave room for Goal Harness.
2. `selected_hard_subset_low`: the public aggregate may be high, but local
   selected cases show Codex goal-mode failures that can be mined safely.
3. `adjacent_agent_low_no_clean_codex`: the benchmark is promising because
   other agents fail often, but a clean Codex goal-mode baseline must be mined
   before treatment.

Runner/setup failures are not model capability failures. They are still P0 when
they block all benchmark progress, but they should not be counted as case-level
Codex weakness until the worker reaches the task.

## Current Codex Baseline Signals

| Rank | Benchmark lane | Evidence class | Codex baseline signal | Current interpretation | Next move |
| --- | --- | --- | --- | --- | --- |
| 1 | SWE-Marathon | `direct_codex_goal_mode_low` | Prior scan records Codex CLI + GPT-5.5 at 12.0% pass@1, and the paper reports no evaluated configuration above 30% pass@1. | Best strategic target for long-horizon state, restartability, self-verification, and premature-stop failures. | Keep as top new-family lane, but require a capacity route before any real run. Local provider preflight found the first candidate under-provisioned. |
| 2 | SkillsBench / skill-runtime lane | `direct_codex_goal_mode_low` | Public SkillsBench reports GPT-5.5 Codex at 46.8% without skills and 66.5% with skills. | Strong direct evidence that skill/context routing can move outcomes. More relevant to Goal Harness skill provenance, safe reuse, negative transfer, and exposure/writeback than Terminal-Bench style terminal work. | Promote to a near-term P1 adapter dossier and baseline-failure mining lane after the current Terminal-Bench runner setup blocker is repaired. |
| 3 | Terminal-Bench selected hard subset | `selected_hard_subset_low` | Official full leaderboard is high for Codex CLI, but the local selected ledger has only 3 passing Codex goal-mode baseline cases among 11 unique selected cases; many failures are setup/model-route blockers rather than task failures. | Keep as the immediate engineering lane because runner, ledger, compact attribution, and worker-bridge surfaces are already wired. Do not treat full Terminal-Bench as low-baseline. | P0 is to repair worker startup/setup timeout first, then mine one attributable baseline failure before treatment. |
| 4 | AgentIssue-Bench | `adjacent_agent_low_no_clean_codex` | Prior scan found no clean official Codex CLI score; published/leaderboard evidence for other agents is only 0.67% to 4.67% correct resolution. | Very high product fit for agent-runtime bugs, provider/tool failures, and workflow repair. Current local pilot showed a source-alignment blocker, not a benchmark-level conclusion. | Keep focused on one selected tag and align patch generation to the buggy source snapshot before any broader run. |
| 5 | PerfBench | `adjacent_agent_low_no_clean_codex` | Prior scan found no direct Codex CLI score; OpenHands-style baseline is about 3%, specialized performance agent about 20%. | Strong validation/profiling loop and likely control-plane leverage, but setup/toolchain cost is less known. | Add setup-readiness and one cheap sample route after Terminal-Bench startup repair and AgentIssue source alignment. |
| 6 | SWE-Bench Pro public | `adjacent_agent_low_no_clean_codex` | Public source is valuable and contamination-resistant, but a clean Codex CLI goal-mode baseline row is not yet established in this repo. | Important later SWE lane, but not the fastest way to prove Goal Harness uplift unless we first find baseline-failing cases under our exact Codex goal-mode surface. | Keep behind a wrapper/descriptor gate and a baseline failure-mining pass. |
| 7 | WildClawBench / APEX / TheAgentCompany / ALE | `adjacent_agent_low_no_clean_codex` | These are promising professional-agent lanes, but the local repo does not yet have direct Codex goal-mode baseline evidence. | Good watchlist and adapter-dossier candidates, not immediate scoring lanes. | Build dossiers only after the current engineering/skill lanes produce stable runner and ledger patterns. |

## Terminal-Bench Local Ledger Recheck

The local selected Terminal-Bench ledger should be interpreted as a hard-case
mining set, not as an aggregate benchmark score:

| Bucket | Cases | Meaning |
| --- | --- | --- |
| Passed Codex goal-mode baseline | `nginx-request-logging`, `path-tracing`, `regex-log` | Not current treatment priority unless a separate control-plane failure is found. |
| Runner/setup blocked | `build-cython-ext`, `financial-document-processor`, `large-scale-text-editing`, `multi-source-data-merger` | Repair the Codex worker startup/model-route path before using these as capability evidence. |
| Attribution gate | `headless-terminal` | Baseline is 0.0 but needs compact verifier attribution before treatment. |
| Case/solution-level failures worth studying | `install-windows-3.11`, `make-doom-for-mips`, `pytorch-model-recovery` | Best current Terminal-Bench candidates for failure-class research once startup alignment is clean. |

Strict selected-case pass rate is 3/11, but that number is deliberately biased
toward hard cases and polluted by runner/setup blockers. The more important
signal is the mix: setup timeout is now the immediate control-plane blocker,
while exception/timeout cases remain the next Goal Harness uplift candidates.

## Updated Priority Order

1. `P0` Repair the Terminal-Bench Codex worker startup/setup path. This unlocks
   every other Terminal-Bench baseline and treatment run and prevents setup
   failures from being mistaken for benchmark difficulty.
2. `P0/P1` After startup repair, rerun exactly one Terminal-Bench P0 case and
   only launch treatment if the baseline failure is compact-attributed and
   control-plane-addressable.
3. `P1` Start the SkillsBench adapter dossier and baseline-failure mining lane.
   It has a direct low Codex CLI baseline and a visible skill-lift axis.
4. `P1` Resume the one-tag AgentIssue-Bench lane only after aligning patch
   generation to the benchmark buggy source snapshot.
5. `P1` Keep SWE-Marathon as the highest strategic low-baseline benchmark, but
   defer real execution until local or remote capacity is proven.
6. `P1/P2` Add PerfBench setup-readiness after the current runner/setup blocker
   is resolved.
7. `P2` Keep SWE-Bench Pro, WildClawBench, APEX, TheAgentCompany, and ALE as
   dossier/watchlist lanes until each has a clean Codex goal-mode baseline
   failure-mining plan.

## Planning Rule

Do not rank benchmark families by public accuracy alone. Rank by:

- low or failure-rich Codex goal-mode baseline evidence;
- whether failures are observable without reading hidden/private material;
- whether Goal Harness could plausibly change the outcome through state,
  todo/checkpoint discipline, validation, replan, tool/skill provenance,
  writeback, or failure attribution;
- setup readiness and no-upload/no-submit safety;
- whether the result can be reduced into `benchmark_run_v0` and the run ledger.
