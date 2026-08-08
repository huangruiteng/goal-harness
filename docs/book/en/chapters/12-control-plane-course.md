# Control-Plane Developer Course

> For developers who plan to modify LoopX Kernel, CLI, state projection,
> scheduler, or extension behavior.

## Relationship to the Dev Book

The Dev Book gives external developers a complete path from mechanism model to
project onboarding or contribution. The Control-Plane Developer Course is an
independent chapter for developers who need to enter implementation source,
judge rule precedence, locate bounded contexts, or add a new control-plane
rule.

Both share the official protocols and source as authority, but do not maintain
two copies of the full course:

- the Dev Book explains enough mechanism to predict behavior;
- the Course provides Showcase derivations, decision tables, source
  walkthroughs, experiments, and review questions.

## Course map

| Course chapter | Topic | Best entry point in the Dev Book |
|---|---|---|
| [Concept primer](/loopx/docs/development/control-plane-course/00-concept-primer/) | Limited context, externalized state, core concepts | After Chapters 1-2 |
| [Long-horizon convergence](/loopx/docs/development/control-plane-course/topic-long-horizon-convergence/) | Direction, evidence, delta, liveness, terminal invariants | After Chapter 6 |
| [Lesson 1: Harness is the effectful program](/loopx/docs/development/control-plane-course/01-agent-loop-effectful-program/) | Harness as the agent-loop effect interpreter | After Chapters 1-6 |
| [Lesson 2: Architecture from three showcases](/loopx/docs/development/control-plane-course/02-goal-control-plane-architecture/) | Agent / Provider / Capability / Kernel ownership | After Chapter 2 |
| [Lesson 3: First real loop](/loopx/docs/development/control-plane-course/03-first-real-loop/) | Guided start, todo, quota, refresh, spend | After Chapters 1-6 |
| [Lesson 4: State substrate](/loopx/docs/development/control-plane-course/04-state-substrate/) | Registry, events, active state, run history, projection | After Chapter 3 |
| [Lesson 5: Work graph and peers](/loopx/docs/development/control-plane-course/05-work-graph-and-peers/) | Claim, lease, handoff, equal peers | After Chapter 4 |
| [Lesson 6: Quota kernel and interaction contract](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/) | `should-run`, route, mode, interaction contract | After Chapter 5 |
| [Lesson 7: Host, heartbeat, stateful backoff](/loopx/docs/development/control-plane-course/07-host-scheduler-and-heartbeat/) | Execution context, RRULE, ACK, backoff | After Chapters 5-6 |
| [Lesson 8: Evidence, refresh, self-repair](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/) | Material progress, replan, repair delta | After Chapter 6 |
| [Lesson 9: Add a control-plane rule](/loopx/docs/development/control-plane-course/09-engineering-a-control-plane-rule/) | Invariants, ordered rules, schemas, smokes | After Chapters 10-13 |
| [Lesson 10: Layered quality gates](/loopx/docs/development/control-plane-course/10-autonomous-agent-quality-gates/) | Deterministic tests, canaries, model behavior, release gates | After Chapter 13 |
| [Lesson 11: Extensions and domain products](/loopx/docs/development/control-plane-course/11-extension-layer/) | Explore, Graph/Harness, domain products | After Chapters 14-16 |

## Relationship to the Effect Interpreter RFC

Lesson 1 and the
[Agent Loop Effect Interpreter RFC](/loopx/docs/architecture/rfcs/agent-loop-effect-interpreter-v0/)
share one language: the harness is the effectful program around an agent loop,
and state machines are interpretation tables. Start with Lesson 1 before
entering Kernel implementation topics.
