from __future__ import annotations

from copy import deepcopy

from loopx.capabilities.pr_review_queue import (
    build_pull_request_review_queue_observation,
)


def _pr(
    number: int,
    *,
    head: str | None = None,
    decision: str = "REVIEW_REQUIRED",
    draft: bool = False,
    merge_state: str = "CLEAN",
    failures: list[str] | None = None,
) -> dict[str, object]:
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/owner/repo/pull/{number}",
        "state": "OPEN",
        "head_oid": head or f"{number:040d}",
        "review_decision": decision,
        "is_draft": draft,
        "merge_state": merge_state,
        "checks": {
            "counts": {
                "success": 1,
                "failure": len(failures or []),
                "pending": 0,
                "unknown": 0,
            },
            "failures": failures or [],
            "pending": [],
        },
    }


def _observe(
    items: list[dict[str, object]],
    *,
    complete: bool = True,
    previous: dict[str, object] | None = None,
    handled: list[str] | None = None,
) -> dict[str, object]:
    return build_pull_request_review_queue_observation(
        repository="owner/repo",
        pull_requests=items,
        result_completeness={"complete": complete},
        previous_observation=previous,
        handled_exact_heads=handled or [],
    )


def test_incomplete_queue_is_not_observed_and_preserves_baseline() -> None:
    baseline = _observe([_pr(1)])
    result = _observe([_pr(1), _pr(2)], complete=False, previous=baseline)

    assert result["observation_state"] == "not_observed"
    assert result["queue_fingerprint"] is None
    assert result["previous_queue_fingerprint"] == baseline["queue_fingerprint"]
    assert result["baseline_preserved"] is True
    assert [item["number"] for item in result["items"]] == [1]
    assert result["queue_size"] is None
    assert result["candidate_count"] == 0
    assert result["candidate"] is None
    assert result["pending_candidate_exact_head"] == f"1@{1:040d}"

    recovered = _observe([_pr(1)], previous=result)
    assert recovered["observation_state"] == "observed_unchanged"
    assert recovered["candidate"] is None

    advanced = _observe(
        [_pr(1), _pr(2)],
        previous=result,
        handled=[f"1@{1:040d}"],
    )
    assert advanced["candidate"]["number"] == 2


def test_initial_complete_observation_selects_one_exact_head_candidate() -> None:
    result = _observe([_pr(1), _pr(2)])

    assert result["observation_state"] == "material_transition"
    assert result["changed_pr_numbers"] == [1, 2]
    assert result["candidate_count"] == 1
    assert result["repository"] == "owner/repo"
    assert result["queue_size"] == 2
    assert all(set(item) == {"number", "fingerprint"} for item in result["items"])
    candidate = result["candidate"]
    assert candidate["number"] == 1
    assert candidate["head_oid"] == f"{1:040d}"
    todo = candidate["todo_preview"]
    assert todo["action_kind"] == "review_pull_request_exact_head"
    assert todo["task_repository"] == "git:github.com/owner/repo"
    assert todo["required_capabilities"] == ["network", "external_evidence_poll"]
    assert result["write_authority_granted"] is False
    assert result["external_write_performed"] is False


def test_unchanged_observation_emits_no_duplicate_candidate() -> None:
    first = _observe([_pr(1), _pr(2)])
    repeated = _observe([_pr(1), _pr(2)], previous=first)

    assert repeated["observation_state"] == "observed_unchanged"
    assert repeated["changed_pr_numbers"] == []
    assert repeated["candidate"] is None
    assert repeated["pending_candidate_exact_head"] == f"1@{1:040d}"


def test_handled_exact_head_advances_unchanged_backlog() -> None:
    first = _observe([_pr(1), _pr(2)])
    handled = [f"1@{1:040d}"]
    repeated = _observe([_pr(1), _pr(2)], previous=first, handled=handled)

    assert repeated["observation_state"] == "observed_unchanged"
    assert repeated["changed_pr_numbers"] == []
    assert repeated["handled_exact_heads"] == handled
    assert repeated["candidate"]["number"] == 2
    assert repeated["candidate_selection_reason"] == "unhandled_backlog_progression"

    still_pending = _observe([_pr(1), _pr(2)], previous=repeated)
    assert still_pending["observation_state"] == "observed_unchanged"
    assert still_pending["candidate"]["number"] == 2


def test_handled_changed_pr_does_not_strand_unchanged_backlog() -> None:
    first = _observe([_pr(1), _pr(2)])
    result = _observe(
        [_pr(1, decision="CHANGES_REQUESTED"), _pr(2)],
        previous=first,
        handled=[f"1@{1:040d}"],
    )

    assert result["observation_state"] == "material_transition"
    assert result["changed_pr_numbers"] == [1]
    assert result["candidate"]["number"] == 2
    assert result["candidate_selection_reason"] == "unhandled_backlog_progression"


def test_new_head_reopens_a_previously_handled_pr() -> None:
    first = _observe([_pr(1), _pr(2)])
    result = _observe(
        [_pr(1, head="f" * 40), _pr(2)],
        previous=first,
        handled=[f"1@{1:040d}"],
    )

    assert result["candidate"]["number"] == 1
    assert result["candidate"]["head_oid"] == "f" * 40
    assert result["candidate_selection_reason"] == "unhandled_material_transition"
    assert result["handled_exact_heads"] == []


def test_closed_handled_pr_advances_and_prunes_cursor() -> None:
    first = _observe([_pr(1), _pr(2)])
    result = _observe(
        [_pr(2)],
        previous=first,
        handled=[f"1@{1:040d}"],
    )

    assert result["removed_pr_numbers"] == ["1"]
    assert result["candidate"]["number"] == 2
    assert result["candidate_selection_reason"] == "unhandled_backlog_progression"
    assert result["handled_exact_heads"] == []


def test_handled_exact_head_must_be_number_and_full_oid() -> None:
    try:
        _observe([_pr(1)], handled=["1@short"])
    except ValueError as exc:
        assert "NUMBER@HEAD_OID" in str(exc)
    else:
        raise AssertionError("invalid handled exact head was accepted")


def test_handled_exact_head_must_match_prior_candidate() -> None:
    first = _observe([_pr(1), _pr(2)])
    try:
        _observe([_pr(1), _pr(2)], previous=first, handled=[f"2@{2:040d}"])
    except ValueError as exc:
        assert "prior candidate" in str(exc)
    else:
        raise AssertionError("an unselected exact head was marked handled")


def test_exact_review_fingerprint_change_selects_changed_pr_only() -> None:
    first = _observe([_pr(1), _pr(2)])
    changed = [_pr(1), _pr(2, decision="CHANGES_REQUESTED", head="f" * 40)]
    result = _observe(changed, previous={"autonomous_review": first})

    assert result["observation_state"] == "material_transition"
    assert result["changed_pr_numbers"] == [2]
    assert result["candidate"]["number"] == 2
    assert (
        result["candidate"]["todo_preview"]["action_kind"]
        == "rereview_pull_request_exact_head"
    )


def test_check_draft_and_mergeability_changes_are_material() -> None:
    first = _observe([_pr(1), _pr(2)])
    changed = [_pr(1), _pr(2, merge_state="BLOCKED", failures=["pytest"])]
    result = _observe(changed, previous=first)
    assert result["changed_pr_numbers"] == [2]
    assert result["candidate"]["number"] == 2

    draft = deepcopy(changed)
    draft[1]["is_draft"] = True
    draft_result = _observe(draft, previous=result)
    assert draft_result["observation_state"] == "material_transition"
    assert draft_result["changed_pr_numbers"] == [2]
    assert draft_result["candidate"] is None


def test_queue_fingerprint_is_repository_scoped() -> None:
    first = build_pull_request_review_queue_observation(
        repository="owner/one",
        pull_requests=[_pr(1)],
        result_completeness={"complete": True},
    )
    second = build_pull_request_review_queue_observation(
        repository="owner/two",
        pull_requests=[_pr(1)],
        result_completeness={"complete": True},
        previous_observation=first,
    )

    assert second["observation_state"] == "material_transition"
    assert second["queue_fingerprint"] != first["queue_fingerprint"]
    assert second["candidate"]["repository"] == "owner/two"


def test_approved_transition_routes_to_merge_policy_without_granting_it() -> None:
    first = _observe([_pr(1)])
    approved = _observe([_pr(1, decision="APPROVED")], previous=first)

    todo = approved["candidate"]["todo_preview"]
    assert todo["action_kind"] == "qualify_pull_request_merge_readiness"
    assert "route any merge through repository policy" in todo["text"]
    assert approved["write_authority_granted"] is False
