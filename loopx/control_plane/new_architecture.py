"""Phase 5 new-architecture master switch.

The Phase 5 control-plane features (unified ``policy_decision``, event-driven
dispatch, heartbeat-as-event-source, and the merged tick) are enabled by default
under a single master switch. Each individual feature can still be forced on or
off via its own environment variable; the priority is:

    explicit feature flag env value  >  master switch  >  off

Concretely, an unset feature flag inherits the master switch value, so setting
``LOOPX_NEW_ARCHITECTURE=1`` turns everything on while ``=0`` turns it all off
(unless a specific feature flag is set explicitly).
"""

from __future__ import annotations

import os

MASTER_ENV = "LOOPX_NEW_ARCHITECTURE"

_TRUTHY = {"1", "true", "yes", "on"}


def master_switch_enabled() -> bool:
    """Whether the new architecture is enabled globally.

    The new architecture is ON by default: an unset ``LOOPX_NEW_ARCHITECTURE``
    enables it. Set ``LOOPX_NEW_ARCHITECTURE=0`` (or ``false``/``no``/``off``)
    to disable it globally; individual feature flags can still override.
    """
    value = os.environ.get(MASTER_ENV, "").strip().lower()
    if not value:
        return True
    return value in _TRUTHY
