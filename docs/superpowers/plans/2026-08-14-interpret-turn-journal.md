# Turn Journal Interpretation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `interpret_turn_journal` Effect Program lens that returns structured replay legality, identity mismatch, tombstone, and phase-order information.

**Architecture:** Keep the public lens in `loopx.control_plane.effect_program` beside the existing quota and Turn-result interpreters. Move the canonical Turn phase sequence into that core Effect Program module and retain `turn_driver.transaction.TRANSACTION_PHASES` as an alias, so interpretation and execution share one exact ordering rule without a circular import or duplicated tuple. Project typed violations into `EffectRequest.context`; never call executor, journal I/O, scheduling, or quota code.

**Tech Stack:** Python 3.12, frozen dataclasses, `StrEnum`, pytest, Markdown reference documentation.

## Global Constraints

- The API is `interpret_turn_journal(journal, *, goal_id=None, agent_id=None, turn_key=None, capabilities=()) -> EffectTurn`.
- Semantic mismatches return `EffectTurn` with `decision="replay_blocked"`; they do not raise.
- `EffectObservation.should_run` is always `False`; `request.context["replay_legal"]` is the legality signal.
- The lens performs no journal I/O, mutation, execution, scheduling, model call, or quota spending.
- Existing journal and Turn wire schemas remain unchanged.
- Terminal replay tombstones are exactly `committed`, `stopped`, and `failed`; failed recovery with `retry_failed=True` remains executor-owned.
- Classification uses typed fields and exact equality, not substring heuristics.

---

### Task 1: Establish The Legal Replay Lens And Canonical Phase Source

**Files:**
- Create: `tests/control_plane/test_effect_turn_turn_journal.py`
- Modify: `loopx/control_plane/effect_program.py`
- Modify: `loopx/control_plane/turn_driver/transaction.py`

**Interfaces:**
- Consumes: existing `EffectRequest`, `EffectInterpretation`, `EffectObservation`, `EffectNext`, and `EffectTurn` dataclasses.
- Produces: `TurnTransactionPhase`, `TURN_TRANSACTION_PHASES`, and `interpret_turn_journal(...) -> EffectTurn`; preserves `turn_driver.transaction.TRANSACTION_PHASES` as the same tuple.

- [ ] **Step 1: Write the failing legal-journal test**

```python
from copy import deepcopy

from loopx.control_plane.effect_program import EffectNext, interpret_turn_journal


def _journal(*, status: str = "committed") -> dict[str, object]:
    turn_key = "sha256:fixture-turn"
    return {
        "schema_version": "loopx_turn_journal_v0",
        "goal_id": "fixture-goal",
        "turn_key": turn_key,
        "status": status,
        "completed_phases": [
            "host_execute",
            "typed_result",
            "validation",
            "durable_writeback",
            "quota_spend",
            "scheduler_apply",
            "scheduler_ack",
        ],
        "plan": {
            "turn_envelope": {
                "goal_id": "fixture-goal",
                "agent_id": "fixture-agent",
            },
            "transaction": {
                "turn_key": turn_key,
                "settlement_plan": {
                    "identity": {
                        "goal_id": "fixture-goal",
                        "agent_id": "fixture-agent",
                    }
                },
            },
        },
        "host_result": {"turn_key": turn_key},
        "receipt": {"turn_key": turn_key},
    }


def test_turn_journal_reports_legal_replay_without_mutating_input() -> None:
    journal = _journal()
    before = deepcopy(journal)

    turn = interpret_turn_journal(
        journal,
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
        capabilities=["filesystem_read"],
    )

    assert turn.request.kind == "turn_journal"
    assert turn.request.source == "turn_journal"
    assert turn.request.context == {
        "replay_legal": True,
        "goal_matches": True,
        "owner_matches": True,
        "turn_key_matches": True,
        "phases_form_ordered_prefix": True,
        "journal_status": "committed",
        "tombstone_retained": True,
        "completed_phases": (
            "host_execute",
            "typed_result",
            "validation",
            "durable_writeback",
            "quota_spend",
            "scheduler_apply",
            "scheduler_ack",
        ),
        "violations": (),
    }
    assert turn.observation.decision == "replay_legal"
    assert turn.observation.should_run is False
    assert turn.next_effect == EffectNext()
    assert journal == before
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest -q tests/control_plane/test_effect_turn_turn_journal.py::test_turn_journal_reports_legal_replay_without_mutating_input`

Expected: collection fails because `interpret_turn_journal` does not exist.

- [ ] **Step 3: Add the canonical phase enum and minimal legal lens**

In `effect_program.py`, define the canonical phases and implement the public signature:

```python
class TurnTransactionPhase(StrEnum):
    HOST_EXECUTE = "host_execute"
    TYPED_RESULT = "typed_result"
    VALIDATION = "validation"
    DURABLE_WRITEBACK = "durable_writeback"
    QUOTA_SPEND = "quota_spend"
    SCHEDULER_APPLY = "scheduler_apply"
    SCHEDULER_ACK = "scheduler_ack"


TURN_TRANSACTION_PHASES = tuple(phase.value for phase in TurnTransactionPhase)


def interpret_turn_journal(
    journal: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    turn_key: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    plan = _mapping(journal.get("plan"))
    envelope = _mapping(plan.get("turn_envelope"))
    transaction = _mapping(plan.get("transaction"))
    settlement = _mapping(transaction.get("settlement_plan"))
    identity = _mapping(settlement.get("identity"))
    completed = tuple(str(value) for value in journal.get("completed_phases", []))
    context = {
        "replay_legal": True,
        "goal_matches": True,
        "owner_matches": True,
        "turn_key_matches": True,
        "phases_form_ordered_prefix": completed
        == TURN_TRANSACTION_PHASES[: len(completed)],
        "journal_status": str(journal.get("status") or ""),
        "tombstone_retained": journal.get("status")
        in {"committed", "stopped", "failed"},
        "completed_phases": completed,
        "violations": (),
    }
    return EffectTurn(
        request=EffectRequest(
            kind="turn_journal",
            source="turn_journal",
            goal_id=goal_id,
            agent_id=agent_id,
            capabilities=tuple(capabilities),
            context=context,
        ),
        interpretation=EffectInterpretation(
            route="turn_journal_replay",
            obligation="observe_fenced_replay",
            interaction_mode="read_only",
        ),
        observation=EffectObservation(
            decision="replay_legal",
            should_run=False,
            effective_action="observe_replay",
            recommended_action="Retain the terminal Turn journal tombstone.",
            protocol_summary="Turn journal replay is legal and effect-free.",
        ),
        next_effect=EffectNext(),
    )
```

In `turn_driver/transaction.py`, import `TURN_TRANSACTION_PHASES` and keep compatibility:

```python
TRANSACTION_PHASES = TURN_TRANSACTION_PHASES
```

- [ ] **Step 4: Run legal-lens and transaction regression tests**

Run: `python -m pytest -q tests/control_plane/test_effect_turn_turn_journal.py tests/test_loopx_turn_transaction.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the legal lens seam**

```bash
git add -- tests/control_plane/test_effect_turn_turn_journal.py loopx/control_plane/effect_program.py loopx/control_plane/turn_driver/transaction.py
git commit -m "feat(effect): interpret legal turn journal replay"
```

### Task 2: Return Typed Violations For Illegal And Tombstone States

**Files:**
- Modify: `tests/control_plane/test_effect_turn_turn_journal.py`
- Modify: `loopx/control_plane/effect_program.py`

**Interfaces:**
- Consumes: `TURN_TRANSACTION_PHASES` and `interpret_turn_journal` from Task 1.
- Produces: `TurnJournalViolation(StrEnum)` and complete structured replay results in `EffectRequest.context`.

- [ ] **Step 1: Add failing identity, phase, terminal, and malformed tests**

Add tests that mutate only controlled fixture fields and assert literal outcomes:

```python
def test_turn_journal_accumulates_identity_and_phase_violations() -> None:
    journal = _journal()
    journal["goal_id"] = "other-goal"
    journal["turn_key"] = "sha256:other-turn"
    journal["completed_phases"] = ["host_execute", "validation"]
    identity = journal["plan"]["transaction"]["settlement_plan"]["identity"]
    identity["agent_id"] = "other-agent"

    turn = interpret_turn_journal(
        journal,
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )

    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["goal_matches"] is False
    assert turn.request.context["owner_matches"] is False
    assert turn.request.context["turn_key_matches"] is False
    assert turn.request.context["phases_form_ordered_prefix"] is False
    assert turn.request.context["violations"] == (
        "goal_mismatch",
        "owner_mismatch",
        "turn_key_mismatch",
        "completed_phases_not_ordered_prefix",
    )
    assert turn.observation.decision == "replay_blocked"
    assert turn.observation.should_run is False


@pytest.mark.parametrize("status", ["committed", "stopped", "failed"])
def test_turn_journal_retains_terminal_tombstones(status: str) -> None:
    turn = interpret_turn_journal(
        _journal(status=status),
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        turn_key="sha256:fixture-turn",
    )
    assert turn.request.context["tombstone_retained"] is True
    assert turn.request.context["journal_status"] == status
    assert turn.request.context["replay_legal"] is True


def test_turn_journal_blocks_non_terminal_and_malformed_trace() -> None:
    journal = {"status": "in_progress", "completed_phases": "host_execute"}
    turn = interpret_turn_journal(journal)
    assert turn.request.context["replay_legal"] is False
    assert turn.request.context["tombstone_retained"] is False
    assert turn.request.context["violations"] == (
        "goal_identity_missing",
        "owner_identity_missing",
        "turn_key_identity_missing",
        "completed_phases_invalid",
        "journal_not_terminal",
    )
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest -q tests/control_plane/test_effect_turn_turn_journal.py`

Expected: tests fail because Task 1 does not yet compare trace identity or classify blocked replay.

- [ ] **Step 3: Implement exact identity comparison and typed violations**

Add the enum and helpers in `effect_program.py`:

```python
class TurnJournalViolation(StrEnum):
    GOAL_IDENTITY_MISSING = "goal_identity_missing"
    GOAL_MISMATCH = "goal_mismatch"
    OWNER_IDENTITY_MISSING = "owner_identity_missing"
    OWNER_MISMATCH = "owner_mismatch"
    TURN_KEY_IDENTITY_MISSING = "turn_key_identity_missing"
    TURN_KEY_MISMATCH = "turn_key_mismatch"
    COMPLETED_PHASES_INVALID = "completed_phases_invalid"
    COMPLETED_PHASES_NOT_ORDERED_PREFIX = "completed_phases_not_ordered_prefix"
    JOURNAL_NOT_TERMINAL = "journal_not_terminal"
    JOURNAL_STATUS_UNSUPPORTED = "journal_status_unsupported"


def _present_strings(*values: Any) -> tuple[str, ...]:
    return tuple(value for item in values if (value := str(item or "").strip()))


def _values_match(values: tuple[str, ...]) -> bool:
    return bool(values) and len(set(values)) == 1
```

Update `interpret_turn_journal` to:

1. require journal/envelope/settlement goal, envelope/settlement owner, and journal/transaction Turn key;
2. append the explicit expectation to each comparison when supplied;
3. compare optional host-result and receipt Turn keys only when present;
4. distinguish non-list phases from list values that are not the canonical prefix;
5. classify `in_progress` and `scheduler_action_required` as known non-terminal state, with unknown values classified as unsupported;
6. set legality from an empty violation list;
7. emit `replay_blocked`, `block_replay`, and domain-neutral readback when any violation exists.

The final legality calculation is:

```python
replay_legal = not violations
context["violations"] = tuple(violation.value for violation in violations)
```

- [ ] **Step 4: Run focused tests and existing Effect Program regressions**

Run: `python -m pytest -q tests/control_plane/test_effect_turn_turn_journal.py tests/control_plane/test_effect_interpreter_packet.py tests/control_plane/test_effect_turn_turn_result.py tests/test_loopx_turn_transaction.py tests/test_loopx_turn_executor.py`

Expected: all tests pass.

- [ ] **Step 5: Commit structured violation behavior**

```bash
git add -- tests/control_plane/test_effect_turn_turn_journal.py loopx/control_plane/effect_program.py
git commit -m "feat(effect): report blocked turn journal replay"
```

### Task 3: Document And Validate The Read-Only Contract

**Files:**
- Modify: `docs/reference/effect-interpreter-packet.md`
- Track: `docs/superpowers/plans/2026-08-14-interpret-turn-journal.md`

**Interfaces:**
- Consumes: final `interpret_turn_journal` behavior from Tasks 1 and 2.
- Produces: public guidance describing identity, tombstone, replay, and no-authority semantics.

- [ ] **Step 1: Update the reference documentation**

Add a `Turn Journal Lens` section that states:

```markdown
## Turn Journal Lens

`interpret_turn_journal` reads an existing fenced Turn journal and returns an
`EffectTurn`. It compares goal, agent owner, and Turn-key identity across the
journal trace; validates that completed phases are an ordered transaction
prefix; and exposes retained terminal tombstones.

`request.context.replay_legal` is the legality signal. `should_run` remains
false and `next_effect` remains empty: interpretation grants no permission to
execute, retry, schedule, write state, or spend quota. Semantic mismatches are
returned as typed violation values instead of exceptions.
```

- [ ] **Step 2: Run formatting and focused validation**

Run:

```powershell
python -m pytest -q tests/control_plane/test_effect_turn_turn_journal.py tests/control_plane/test_effect_interpreter_packet.py tests/control_plane/test_effect_turn_turn_result.py tests/test_loopx_turn_transaction.py tests/test_loopx_turn_executor.py
python examples/loopx-turn-fake-host-walkthrough-smoke.py
loopx check --scan-path docs/reference/effect-interpreter-packet.md --scan-path CONTRIBUTOR_TASKS.md
loopx canary premerge --from-git-diff --git-diff-base upstream/main
git diff --check upstream/main...HEAD
```

Expected: every command exits zero. If the canary reports an explicit skip, record the skip and its reason rather than claiming that surface was tested.

- [ ] **Step 3: Run the public/private boundary scan**

Run:

```powershell
git diff --name-only upstream/main...HEAD
git diff upstream/main...HEAD | Select-String -Pattern 'credential|secret|private state|raw log|trajectory|verifier output|[A-Z]:\\|file://|localhost' -CaseSensitive:$false
```

Expected: only the scoped product, test, reference, spec, and plan files appear; no credential, private-state, raw-evidence, local-path, or internal-link content is present.

- [ ] **Step 4: Commit documentation and plan**

```bash
git add -- docs/reference/effect-interpreter-packet.md docs/superpowers/plans/2026-08-14-interpret-turn-journal.md
git commit -m "docs(effect): explain turn journal replay lens"
```

- [ ] **Step 5: Verify the final branch state**

Run:

```powershell
git status --short --branch
git log --oneline upstream/main..HEAD
```

Expected: the worktree is clean and the scoped commits are listed.
