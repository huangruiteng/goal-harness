from __future__ import annotations

from loopx.heartbeat_prompt import build_heartbeat_prompt


def test_visible_goal_keeps_final_todo_nonterminal_until_spend() -> None:
    payload = build_heartbeat_prompt(
        goal_id="terminal-settlement-fixture",
        thin=True,
        runtime_profile="codex_app_ssh_goal",
    )
    task_body = " ".join(payload["task_body"].split())

    terminal_rule = (
        "Done -> successor first; final -> accountable refresh, spend, then "
        "no-follow-up completion."
    )
    refresh = "refresh the accountable progress record before spending"
    spend = "Then spend exactly once against that refresh"

    assert task_body.index(terminal_rule) < task_body.index(refresh)
    assert task_body.index(refresh) < task_body.index(spend)
    assert payload["interface_budget"]["within_budget"] is True
