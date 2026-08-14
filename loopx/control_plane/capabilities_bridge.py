"""Bridge the legacy capability-pack system into the new control plane.

The legacy ``loopx/capabilities`` system exposes self-contained *capability
packs* (``issue-fix``, ``change-quality-qualification``, ``pull-request-review``,
...). Each pack declares, via ``catalog.py``, an ``entry_command`` and an ordered
``commands[]`` pipeline where every command carries a ``purpose`` and a
``write_boundary``. The new control plane models capability as *tokens*
(``required_capabilities`` / ``target_capabilities`` on todos) matched against a
worker's declared tokens in ``eligible(worker, task)``.

This module closes the gap in three stages (see ``plan/`` for the design):

P1 — capability packs enter ``eligible``: unify capability-token normalization
     and let a task's ``capability_binding_ref`` resolve through the
     ``CapabilityRegistry`` provider lifecycle (declared/installed/enabled/ready).

P2 — capability packs self-register their CLI: a registry-driven command
     registry so capability packs no longer need static ``import`` wiring in
     ``cli.py``.

P3 — capability-pack hooks become event subscriptions: a minimal event
     subscription hub over the existing ``rollout_event_log`` event kinds so
     legacy hooks (projection / decision-input) can be re-attached as
     subscribers instead of being hard-coded into quota/configure_goal/etc.

All three stages are written defensively against the *variety* of capability
packs in ``catalog.BUILTIN_CAPABILITIES``: missing ``commands``, missing
``workflow_skill``, missing ``default_enabled``, and internal-only packs are all
tolerated.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .todos.contract import (
    TODO_CAPABILITY_BINDING_REF_PATTERN,
    TODO_CAPABILITY_PATTERN,
)


# ---------------------------------------------------------------------------
# Shared token normalization (P1)
# ---------------------------------------------------------------------------


def capability_token(value: Any) -> str | None:
    """Normalize a capability-pack id or raw token to a public-safe token.

    Returns ``None`` when the value cannot form a valid capability token, which
    lets callers safely skip unknown/malformed inputs instead of crashing on a
    capability pack they do not understand.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    # Collapse hyphen/space separators to underscores, same as the todo contract.
    text = text.replace("-", "_").replace(" ", "_")
    if not TODO_CAPABILITY_PATTERN.fullmatch(text):
        return None
    return text


def capability_token_set(values: Any) -> set[str]:
    """Normalize a list/CSV/string of capability tokens to a token set."""
    result: set[str] = set()
    if isinstance(values, str):
        raw = values.replace(",", " ").split()
    elif isinstance(values, (list, tuple, set)):
        raw = values  # type: ignore[assignment]
    else:
        return result
    for item in raw:
        token = capability_token(item)
        if token:
            result.add(token)
    return result


def split_binding_ref(binding_ref: str | None) -> tuple[str, str] | None:
    """Split ``namespace:value`` into ``(namespace, value)``, or None.

    The namespace is expected to be a capability-pack id (``issue-fix``); the
    value is a pack-local key (``feasibility_v0``).
    """
    if not binding_ref:
        return None
    text = str(binding_ref).strip().lower()
    if not TODO_CAPABILITY_BINDING_REF_PATTERN.fullmatch(text):
        return None
    namespace, _, value = text.partition(":")
    return namespace, value


# ---------------------------------------------------------------------------
# P1: registry-driven eligibility
# ---------------------------------------------------------------------------


def _capability_pack_states(registry: Any, include_internal: bool) -> dict[str, dict[str, bool]]:
    """Map capability-pack id -> provider lifecycle state from a registry.

    Keys are the raw pack ids (e.g. ``issue-fix``). Works against any object
    exposing ``records(include_internal=...)`` returning records that carry
    ``provider_state`` (the ``CapabilityRegistry`` contract). Returns an empty
    dict if the registry is unavailable, so eligibility degrades gracefully to
    token-only matching.
    """
    states: dict[str, dict[str, bool]] = {}
    if registry is None:
        return states
    try:
        records = registry.records(include_internal=include_internal)
    except (AttributeError, TypeError, ValueError):
        return states
    for record in records:
        if not isinstance(record, Mapping):
            continue
        rid = record.get("id")
        provider_state = record.get("provider_state") or {}
        states[str(rid)] = {
            key: bool(provider_state.get(key)) for key in ("declared", "installed", "enabled", "ready")
        }
    return states


def capability_pack_ready(registry: Any, capability_id: str, *, include_internal: bool = False) -> bool:
    """Whether a capability pack is ``ready`` in its provider lifecycle.

    Accepts either the raw id (``issue-fix``) or its normalized token
    (``issue_fix``). A pack that is not registered at all is considered *not
    ready* (fail closed), so a task bound to an unknown/disabled pack is not
    claimable.
    """
    states = _capability_pack_states(registry, include_internal)
    # Build a token->id index so both spellings resolve to the same record.
    by_token: dict[str, str] = {}
    for rid in states:
        token = capability_token(rid)
        if token:
            by_token.setdefault(token, rid)
    token = capability_token(capability_id)
    if token is None:
        return False
    raw_id = by_token.get(token)
    if raw_id is None:
        return False
    state = states.get(raw_id)
    return bool(state and state.get("ready", False))


def resolve_required_tokens(task: Mapping[str, Any], *, registry: Any = None) -> list[str]:
    """Resolve a task's effective required capability tokens.

    Merges the task's explicit ``required_capabilities`` with the capability
    pack referenced by its ``capability_binding_ref`` (when present). The pack id
    is added as an additional required token so workers must declare it to claim
    the task.
    """
    tokens: list[str] = []
    seen: set[str] = set()

    for token in capability_token_set(task.get("required_capabilities")):
        if token not in seen:
            seen.add(token)
            tokens.append(token)

    binding = split_binding_ref(task.get("capability_binding_ref"))
    if binding is not None:
        pack_token = capability_token(binding[0])
        if pack_token and pack_token not in seen:
            seen.add(pack_token)
            tokens.append(pack_token)

    return tokens


def eligible_bridged(
    worker: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    registry: Any = None,
) -> bool:
    """Capability-pack-aware eligibility.

    Extends plain token matching with two rules:

    * a ``capability_binding_ref`` contributes the pack id as a required token;
    * when a registry is supplied, a bound pack must be ``ready``, otherwise the
      task is not claimable (fail closed).

    With no binding and no registry this reduces to the original token matching.
    """
    required = resolve_required_tokens(task, registry=registry)
    worker_tokens = capability_token_set(worker.get("capabilities"))

    binding = split_binding_ref(task.get("capability_binding_ref"))
    if binding is not None and registry is not None:
        if not capability_pack_ready(registry, binding[0]):
            return False

    if not required:
        return True
    return all(token in worker_tokens for token in required)


# ---------------------------------------------------------------------------
# P2: registry-driven command registration
# ---------------------------------------------------------------------------

# A capability pack's CLI self-registration hook. Legacy packs expose
# ``register_<name>_commands(subparsers, add_subcommand_format)`` and
# ``handle_<name>_command(args, ...)``. To avoid static imports, the bridge
# calls ``register_commands`` (a single canonical entrypoint) when present, and
# falls back to ``register_<id>_commands``. Both are invoked with
# ``(subparsers, add_subcommand_format)`` because the legacy CLI injects a
# shared ``--format`` helper into every subcommand parser.
CommandRegistrar = Callable[[Any, Any], None]
CommandHandler = Callable[[Any], Any]


def _candidate_cli_modules(record: Mapping[str, Any], capability_id: str) -> list[tuple[str, str]]:
    """Candidate ``(cli_module_path, pkg)`` pairs for a capability-pack record.

    Capability-pack ids are kebab-case but do **not** map 1:1 to CLI module
    names (``pull-request-review`` lives in ``pr_review_queue.cli``;
    ``integration-branch-reconcile`` in ``integration_branch.cli``). The reliable
    source is the record's ``implemented_protocols[].module``, which names a
    real module inside the pack (``loopx.capabilities.<pkg>.<leaf>``). We derive
    the pack package from the first such module and try ``<pkg>.cli`` first, then
    fall back to an id-derived snake-case path for packs without protocols. The
    package name is returned alongside the path so the fallback registrar name
    can be derived from the package (not the id).
    """
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for protocol in record.get("implemented_protocols") or []:
        if not isinstance(protocol, Mapping):
            continue
        module = str(protocol.get("module") or "").strip()
        if not module.startswith("loopx.capabilities."):
            continue
        remainder = module[len("loopx.capabilities."):]
        parts = [p for p in remainder.split(".") if p]
        if not parts:
            continue
        pkg = parts[0]
        path = f"loopx.capabilities.{pkg}.cli"
        if path not in seen:
            seen.add(path)
            candidates.append((path, pkg))
    token = capability_token(capability_id)
    if token and ":" not in token:
        path = f"loopx.capabilities.{token}.cli"
        if path not in seen:
            candidates.append((path, token))
    return candidates


def _find_registrar(module: Any) -> CommandRegistrar | None:
    """Find a ``register_commands`` / ``register_*_commands`` callable.

    The canonical entrypoint is ``register_commands``. Legacy packs instead use a
    per-pack ``register_<name>_commands`` whose ``<name>`` does **not** follow a
    single rule (``change_quality`` -> ``register_change_quality_commands`` but
    ``value_connectors`` -> ``register_value_connector_commands``). We therefore
    reflect over the module for any ``register_*_commands`` callable instead of
    guessing the name, which is what keeps the bridge compatible with the full
    capability variety.
    """
    registrar = getattr(module, "register_commands", None)
    if callable(registrar):
        return registrar
    for name in dir(module):
        if not name.startswith("register_") or not name.endswith("_commands"):
            continue
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def discover_cli_registrars(
    capability_records: Iterable[Mapping[str, Any]],
) -> dict[str, CommandRegistrar]:
    """Discover ``register_commands`` callables from capability-pack records.

    ``capability_records`` are registry records (each carrying ``id`` and, when
    present, ``implemented_protocols``). Returns a ``{capability_id: registrar}``
    map. Missing modules, missing entrypoints, import errors, and packs without
    a CLI are all skipped — this tolerance is what keeps the bridge compatible
    with the full capability variety (some packs have no CLI at all).
    """
    import importlib

    registrars: dict[str, CommandRegistrar] = {}
    for record in capability_records:
        if not isinstance(record, Mapping):
            continue
        capability_id = str(record.get("id") or "").strip()
        if not capability_id:
            continue
        for module_path, _pkg in _candidate_cli_modules(record, capability_id):
            try:
                module = importlib.import_module(module_path)
            except (ImportError, AttributeError):
                continue
            registrar = _find_registrar(module)
            if registrar is not None:
                registrars[capability_id] = registrar
                break
    return registrars


def _registrar_accepts_second_arg(registrar: CommandRegistrar) -> bool:
    """Whether ``registrar`` accepts a second positional argument.

    Decides the arity up front with ``inspect.signature`` instead of probing
    with a trial call, which would re-invoke a two-arg registrar that raises
    ``TypeError`` *inside* its body. When the signature cannot be introspected
    (builtins, opaque callable objects) it falls back to the legacy two-arg
    shape.
    """
    try:
        signature = inspect.signature(registrar)
    except (TypeError, ValueError):
        return True
    try:
        signature.bind(None, None)
    except TypeError:
        return False
    return True


def register_all_capability_commands(
    subparsers: Any,
    add_subcommand_format: Any = None,
    *,
    registry: Any = None,
    capability_records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, CommandRegistrar]:
    """Register every capability pack's CLI commands onto ``subparsers``.

    Capability packs are discovered from ``registry.records()`` (or the explicit
    ``capability_records``), so they live in one place and no longer need static
    ``import`` wiring. Each registrar is invoked with
    ``(subparsers, add_subcommand_format)`` so it can attach the shared
    ``--format`` helper exactly like the legacy wiring did, except registrars
    whose signature only accepts ``subparsers`` are called with a single
    argument. Returns the ``{capability_id: registrar}`` map that was wired up.
    """
    if capability_records is None:
        capability_records = []
        if registry is not None:
            try:
                capability_records = registry.records(include_internal=False)
            except (AttributeError, TypeError, ValueError):
                capability_records = []
    registrars = discover_cli_registrars(capability_records)
    for registrar in registrars.values():
        if _registrar_accepts_second_arg(registrar):
            registrar(subparsers, add_subcommand_format)
        else:
            registrar(subparsers)
    return registrars


# ---------------------------------------------------------------------------
# P3: event subscription hub
# ---------------------------------------------------------------------------


class CapabilityEventHub:
    """A minimal event-subscription hub for capability-pack hooks.

    Legacy capability-pack hooks were hard-coded into ``quota.py``,
    ``configure_goal.py``, ``pr_review.py``, etc. This hub lets them re-attach as
    subscribers keyed by the existing ``rollout_event_log`` event kinds
    (``pr_merge``, ``pr_review_ack``, ``task_completed``, ...), so they no longer
    need to be imported at the call site.

    Subscribers are ``callable(event)`` and may return a projection dict (for
    projection hooks) or a decision input dict (for decision hooks). Unknown
    event kinds are ignored rather than raising, keeping the hub tolerant of
    packs that subscribe to events that never fire.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[str, Callable[[Mapping[str, Any]], Any]]]] = {}

    def subscribe(self, event_kind: str, subscriber: Callable[[Mapping[str, Any]], Any], *, source: str = "") -> None:
        """Attach ``subscriber`` to ``event_kind`` (idempotent per source)."""
        kind = str(event_kind or "").strip()
        if not kind:
            return
        bucket = self._subscribers.setdefault(kind, [])
        existing = any(s == source and fn is subscriber for s, fn in bucket)
        if not existing:
            bucket.append((source, subscriber))

    def publish(self, event_kind: str, event: Mapping[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
        """Deliver ``event`` to all subscribers of ``event_kind``.

        Returns ``(results, errors)``: ``results`` holds the non-None subscriber
        return values; ``errors`` lists ``{"source", "error", "event_kind"}``
        dicts for subscribers that raised. Errors are reported separately so a
        caller can distinguish a broken subscriber from a legitimate result
        without sniffing for an ``"error"`` key. A raising subscriber is isolated
        so one broken hook does not break delivery to the rest.
        """
        kind = str(event_kind or "").strip()
        results: list[Any] = []
        errors: list[dict[str, Any]] = []
        for source, subscriber in self._subscribers.get(kind, []):
            try:
                result = subscriber(event)
            except Exception as exc:  # noqa: BLE001 - isolate subscriber failures
                errors.append({"source": source, "error": str(exc), "event_kind": kind})
                continue
            if result is not None:
                results.append(result)
        return results, errors

    def subscribers_for(self, event_kind: str) -> list[Callable[[Mapping[str, Any]], Any]]:
        return [fn for _, fn in self._subscribers.get(str(event_kind or "").strip(), [])]

    def kinds(self) -> list[str]:
        return sorted(self._subscribers)


# A capability-pack lifecycle hook: ``callable(**kwargs) -> dict``. The hook
# returns a result dict that the host flow merges into its own payload, so a
# pack can contribute a projection or a decision input without the host needing
# to know its concrete type.
CapabilityHook = Callable[..., Mapping[str, Any]]


class CapabilityHookRegistry:
    """A registry of capability-pack lifecycle hooks.

    Legacy packs were imported and called directly inside ``quota.py``,
    ``configure_goal.py``, ``heartbeat_prequota.py``, etc. This registry lets the
    same hooks register under a named *hook point* (``pre_quota``, ``goal_policy``,
    ...) so host flows can collect and run them without a static import — the
    capability pack self-registers instead of being wired in by hand.

    Registration is per (hook_point, source) and idempotent. Each hook is invoked
    with keyword arguments and may raise; the runner isolates exceptions so one
    broken pack does not break the rest, mirroring the tolerance of the event
    hub.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[str, CapabilityHook]]] = {}

    def register(self, hook_point: str, hook: CapabilityHook, *, source: str = "") -> None:
        """Register ``hook`` under ``hook_point`` (idempotent per source)."""
        point = str(hook_point or "").strip()
        if not point or not callable(hook):
            return
        bucket = self._hooks.setdefault(point, [])
        if not any(s == source and fn is hook for s, fn in bucket):
            bucket.append((source, hook))

    def hooks_for(self, hook_point: str) -> list[CapabilityHook]:
        return [fn for _, fn in self._hooks.get(str(hook_point or "").strip(), [])]

    def run(self, hook_point: str, **kwargs: Any) -> list[Mapping[str, Any]]:
        """Run every hook under ``hook_point`` with ``kwargs``.

        Returns the list of hook result dicts. A raising hook contributes an
        ``{"ok": False, "error": ...}`` result instead of aborting the run.
        """
        results: list[Mapping[str, Any]] = []
        for hook in self.hooks_for(hook_point):
            try:
                result = hook(**kwargs)
            except Exception as exc:  # noqa: BLE001 - isolate hook failures
                results.append({"ok": False, "error": str(exc), "hook_point": hook_point})
                continue
            if isinstance(result, Mapping):
                results.append(dict(result))
        return results

    def hook_points(self) -> list[str]:
        return sorted(self._hooks)


__all__ = [
    "capability_token",
    "capability_token_set",
    "split_binding_ref",
    "capability_pack_ready",
    "resolve_required_tokens",
    "eligible_bridged",
    "discover_cli_registrars",
    "register_all_capability_commands",
    "CapabilityEventHub",
    "CapabilityHookRegistry",
]
