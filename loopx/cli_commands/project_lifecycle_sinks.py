from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path

from ..extensions.runtime import (
    default_extension_state_file,
    resolve_extension_activation,
)
from ..history import load_registry
from ..paths import resolve_runtime_root


def lark_explore_graph_syncer(
    runtime_root_arg: str | None,
    *,
    registry_path: Path,
) -> Callable[..., Mapping[str, object]]:
    extension_runtime_root = resolve_runtime_root(
        load_registry(registry_path), runtime_root_arg
    )

    def sync(**kwargs: object) -> Mapping[str, object]:
        implementation = import_module(
            "loopx.extensions.lark.presentation.explore_results"
        )
        preview_kwargs = dict(kwargs)
        preview_kwargs["execute"] = False
        preview = dict(
            implementation.sync_issue_fix_explore_on_material_change(
                **preview_kwargs
            )
        )
        if preview.get("status") in {"not_applicable", "not_configured"}:
            return preview

        provider = import_module("loopx.extensions.lark")
        activation = resolve_extension_activation(
            str(provider.LARK_EXTENSION_ID),
            state_file=default_extension_state_file(extension_runtime_root),
            required_permissions=(str(provider.LARK_PROJECTION_SINK_PERMISSION),),
        )
        result = (
            dict(implementation.sync_issue_fix_explore_on_material_change(**kwargs))
            if kwargs.get("execute")
            else preview
        )
        result["extension_activation"] = activation
        return result

    return sync


def apply_external_sink_postcondition(
    payload: dict[str, object],
    *,
    sink_result: Mapping[str, object],
    warning: str,
    error: str,
) -> None:
    postcondition = (
        sink_result.get("delivery_postcondition")
        if isinstance(sink_result.get("delivery_postcondition"), Mapping)
        else {}
    )
    if not sink_result.get("enabled") or postcondition.get("satisfied"):
        return
    payload.setdefault("warnings", []).append(warning)
    if postcondition.get("blocks_delivery"):
        payload["ok"] = False
        payload["error"] = error
