from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from loopx.capabilities.explore.episode_runtime import (
    RECOVERABLE_EPISODE_MODE,
    recoverable_episode_mode,
)
from loopx.capabilities.explore.harness_runtime import run_budget_arm
from loopx.capabilities.explore.replay_runtime import (
    REPLAYABLE_EPISODE_V2_MODE,
    AdapterStateLease,
    CaptureReplayStateRequest,
    EquivalenceCheck,
    EquivalenceReport,
    ReplayFidelity,
    RestoreReceipt,
    RestoreReplayStateRequest,
    replayable_episode_v2_mode,
)


def _seed(item_id: str = "seed-alpha") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "family": "alpha",
        "concurrency_key": "application:alpha",
    }


def _records(arm: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        record
        for epoch in arm["epochs"]
        for lane in epoch["lanes"]
        for record in lane["results"]
    ]


class LegacyAdapter:
    def list_seed_items(self) -> list[dict[str, Any]]:
        return [_seed("legacy-seed")]

    def execute(self, item: dict[str, Any], **_: Any) -> dict[str, Any]:
        return {
            "item_id": item["item_id"],
            "family": item["family"],
            "observation_keys": ["legacy-observation"],
            "weighted_flags": {},
            "accepted": True,
            "duration_minutes": 0.2,
        }


class DualProtocolAdapter:
    def __init__(self) -> None:
        self.v1_prepare_calls = 0
        self.v1_execute_calls = 0
        self.v1_release_calls = 0
        self.v2_capture_calls = 0
        self._v1_handle = object()
        self._v2_binding = object()

    def list_seed_items(self) -> list[dict[str, Any]]:
        return [_seed()]

    def prepare_episode_group(
        self,
        seed_item: dict[str, Any],
        episode_items: list[dict[str, Any]],
        **_: Any,
    ) -> dict[str, Any]:
        del episode_items
        self.v1_prepare_calls += 1
        return {
            "handle": self._v1_handle,
            "checkpoint_ref": "opaque-v1-checkpoint",
            "prefix_record": {
                "family": seed_item["family"],
                "observation_keys": ["v1-prefix"],
                "weighted_flags": {},
                "accepted": True,
                "duration_minutes": 0.4,
            },
        }

    def execute_episode(
        self,
        handle: object,
        item: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        assert handle is self._v1_handle
        self.v1_execute_calls += 1
        return {
            "item_id": item["item_id"],
            "family": item["family"],
            "observation_keys": ["v1-suffix"],
            "weighted_flags": {},
            "accepted": True,
            "duration_minutes": 0.2,
        }

    def release_episode_group(self, handle: object, **_: Any) -> None:
        assert handle is self._v1_handle
        self.v1_release_calls += 1

    def capture_replay_state(
        self,
        request: CaptureReplayStateRequest,
    ) -> AdapterStateLease:
        del request
        self.v2_capture_calls += 1
        return AdapterStateLease(
            binding_key=self._v2_binding,
            fidelity=ReplayFidelity.SEMANTIC_EQUIVALENT,
            projection_digest="dual-state",
        )

    def restore_replay_state(
        self,
        binding_key: object,
        request: RestoreReplayStateRequest,
    ) -> RestoreReceipt:
        del request
        assert binding_key is self._v2_binding
        return RestoreReceipt(
            achieved_fidelity=ReplayFidelity.SEMANTIC_EQUIVALENT,
            restored_projection_digest="dual-state",
        )

    def validate_replay_equivalence(
        self,
        binding_key: object,
        receipt: RestoreReceipt,
    ) -> EquivalenceReport:
        assert binding_key is self._v2_binding
        return EquivalenceReport(
            achieved_fidelity=receipt.achieved_fidelity,
            equivalent=True,
            expected_digest="dual-state",
            observed_digest=receipt.restored_projection_digest,
            checks=(EquivalenceCheck("dual-state-equivalent", True),),
        )

    def release_replay_state(self, binding_key: object) -> None:
        assert binding_key is self._v2_binding


def test_legacy_adapter_output_and_metrics_remain_standalone(tmp_path: Path) -> None:
    adapter = LegacyAdapter()
    assert recoverable_episode_mode(adapter) is None
    assert replayable_episode_v2_mode(adapter) is None

    arm = run_budget_arm(
        adapter,
        arm_key="legacy-compatibility",
        run_root=tmp_path,
        budget_minutes=1.0,
        worker_count=1,
        max_epochs=1,
        duration_guard_factor=0.0,
    )

    records = _records(arm)
    assert len(records) == 1
    assert "record_kind" not in records[0]
    assert "prefix_reused" not in records[0]
    assert arm["execution_metrics"] == {
        "shared_prefix_compute_minutes": 0.0,
        "episode_suffix_compute_minutes": 0.0,
        "standalone_compute_minutes": 0.2,
        "effective_compute_minutes": 0.2,
        "avoided_recompute_minutes": 0.0,
        "successful_avoided_recompute_minutes": 0.0,
        "episode_group_count": 0,
        "episode_count": 0,
        "episode_error_count": 0,
    }


def test_dual_protocol_adapter_keeps_v1_harness_path_unchanged(
    tmp_path: Path,
) -> None:
    adapter = DualProtocolAdapter()
    assert recoverable_episode_mode(adapter) == RECOVERABLE_EPISODE_MODE
    assert replayable_episode_v2_mode(adapter) == REPLAYABLE_EPISODE_V2_MODE

    arm = run_budget_arm(
        adapter,
        arm_key="dual-protocol-v1",
        run_root=tmp_path,
        budget_minutes=1.0,
        worker_count=1,
        max_epochs=1,
        duration_guard_factor=0.0,
    )

    assert adapter.v1_prepare_calls == 1
    assert adapter.v1_execute_calls == 1
    assert adapter.v1_release_calls == 1
    assert adapter.v2_capture_calls == 0
    assert [record["record_kind"] for record in _records(arm)] == [
        "shared_prefix",
        "episode_suffix",
    ]
    assert arm["execution_metrics"]["effective_compute_minutes"] == 0.6


def test_partial_v2_protocol_fails_closed_without_affecting_v1_detection() -> None:
    class PartialV2Adapter:
        def capture_replay_state(self, *_: Any, **__: Any) -> None:
            return None

    adapter = PartialV2Adapter()
    assert recoverable_episode_mode(adapter) is None
    with pytest.raises(ValueError, match="must implement all protocol methods"):
        replayable_episode_v2_mode(adapter)
