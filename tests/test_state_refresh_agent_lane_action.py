from __future__ import annotations

from loopx.state_refresh import (
    RECOMMENDED_ACTION_SOURCE_ACTIVE_NEXT_ACTION,
    RECOMMENDED_ACTION_SOURCE_AGENT_LANE_SELECTED_TODO,
    derive_recommended_action_with_source,
)

TWO_AGENT_STATE = """# Active Goal State

## Next Action

- Publish agent B's release checklist

## Agent Todo

- [ ] [P1] continue agent A scheduler coverage fix
  <!-- loopx:todo status=open task_class=advancement_task claimed_by=agent-a todo_id=todo_a1 -->
- [ ] [P1] polish agent B release notes
  <!-- loopx:todo status=open task_class=advancement_task claimed_by=agent-b todo_id=todo_b1 -->

## Completed Work Archive
"""


def test_agent_scoped_derivation_prefers_own_lane_todo() -> None:
    action, source = derive_recommended_action_with_source(
        TWO_AGENT_STATE, agent_id="agent-a"
    )
    assert action == "[P1] continue agent A scheduler coverage fix"
    assert source == RECOMMENDED_ACTION_SOURCE_AGENT_LANE_SELECTED_TODO


def test_peer_lane_never_shadows_own_selection() -> None:
    action, source = derive_recommended_action_with_source(
        TWO_AGENT_STATE, agent_id="agent-b"
    )
    assert action == "[P1] polish agent B release notes"
    assert source == RECOMMENDED_ACTION_SOURCE_AGENT_LANE_SELECTED_TODO


def test_agent_without_claimed_todo_falls_back_to_shared_section() -> None:
    action, source = derive_recommended_action_with_source(
        TWO_AGENT_STATE, agent_id="agent-c"
    )
    assert action == "Publish agent B's release checklist"
    assert source == RECOMMENDED_ACTION_SOURCE_ACTIVE_NEXT_ACTION


def test_unscoped_derivation_keeps_shared_section_priority() -> None:
    action, source = derive_recommended_action_with_source(TWO_AGENT_STATE)
    assert action == "Publish agent B's release checklist"
    assert source == RECOMMENDED_ACTION_SOURCE_ACTIVE_NEXT_ACTION
