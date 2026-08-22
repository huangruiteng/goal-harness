from __future__ import annotations

import json

from loopx.capabilities.benchmark_toolkit.reward_contract import (
    verify_verifier_reward_file,
    verify_verifier_reward_json,
)


def test_numeric_reward_passes() -> None:
    receipt = verify_verifier_reward_json(
        {"reward": 0.0, "score": 0.0, "success_rate": 0.0}
    )
    assert receipt["valid"] is True
    assert receipt["reason_code"] == "ok"
    assert receipt["invalid_keys"] == []


def test_string_detail_rejected() -> None:
    receipt = verify_verifier_reward_json(
        {"reward": 0.0, "detail": "widesearch official evaluator"}
    )
    assert receipt["valid"] is False
    assert receipt["reason_code"] == "reward_non_numeric_values"
    assert receipt["invalid_keys"] == ["detail"]


def test_nested_and_bool_rejected() -> None:
    receipt = verify_verifier_reward_json({"reward": {"value": 1}})
    assert receipt["valid"] is False
    assert receipt["invalid_keys"] == ["reward"]

    receipt_bool = verify_verifier_reward_json({"reward": True})
    assert receipt_bool["valid"] is False


def test_non_finite_float_rejected() -> None:
    receipt = verify_verifier_reward_json({"reward": float("nan")})
    assert receipt["valid"] is False


def test_file_round_trip(tmp_path) -> None:
    good = tmp_path / "reward.json"
    good.write_text(json.dumps({"reward": 0.0}), encoding="utf-8")
    assert verify_verifier_reward_file(good)["valid"] is True

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"reward": "oops"}), encoding="utf-8")
    assert verify_verifier_reward_file(bad)["valid"] is False

    assert verify_verifier_reward_file(tmp_path / "missing.json")["reason_code"] == (
        "reward_file_missing"
    )

    malformed = tmp_path / "malformed.json"
    malformed.write_text("not json", encoding="utf-8")
    assert verify_verifier_reward_file(malformed)["reason_code"] == (
        "reward_file_invalid"
    )


def test_too_many_entries_rejected() -> None:
    receipt = verify_verifier_reward_json(
        {f"k{i}": 1.0 for i in range(65)}
    )
    assert receipt["valid"] is False
    assert receipt["reason_code"] == "reward_too_many_entries"


def test_non_object_rejected() -> None:
    receipt = verify_verifier_reward_json([1, 2])  # type: ignore[arg-type]
    assert receipt["valid"] is False
    assert receipt["reason_code"] == "reward_not_object"
