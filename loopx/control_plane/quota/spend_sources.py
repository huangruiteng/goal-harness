from __future__ import annotations


DEFAULT_SLOT_SPEND_SOURCE = "heartbeat"
VISIBLE_GOAL_SLOT_SPEND_SOURCE = "visible-goal"
VALID_SLOT_SPEND_SOURCES = {
    "heartbeat",
    "controller",
    "adapter",
    VISIBLE_GOAL_SLOT_SPEND_SOURCE,
}
