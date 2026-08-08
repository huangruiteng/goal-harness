from __future__ import annotations

"""Pure quota policy constants owned by the quota read model.

``loopx.quota`` re-exports these names for compatibility. No module in this
file may import from ``loopx.quota``.
"""


DEFAULT_COMPUTE_QUOTA = 1.0
DEFAULT_WINDOW_HOURS = 24
DEFAULT_SLOT_MINUTES = 1

FOCUS_WAIT_LIFECYCLE_MARKERS = {
    "continuation_boundary",
    "focus_wait",
}

FOCUS_WAIT_REASON = (
    "focus wait: delivery lane has a continuation boundary or missing novelty; "
    "wait for new evidence, owner input, external eval, or a clean baseline before "
    "spending delivery compute"
)

AUTONOMOUS_CANDIDATE_CONTEXT_FIELDS = (
    "source",
    "open_count",
    "task_class",
    "items",
)

SELF_REPAIR_SPEND_ACTIONS = {
    "control_plane_health_repair",
    "control_plane_projection_repair",
    "state_projection_gap_repair",
    "boundary_projection_repair",
    "todo_decision_scope_projection_repair",
}

MONITOR_DUE_ITEM_LIMIT = 1
