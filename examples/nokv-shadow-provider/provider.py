"""NoKV byte-CAS coordination provider for the shared-goal authority RFC.

Storage adapter only. Domain semantics, receipts, and head validation belong
to the production authority modules under
``loopx.control_plane.coordination``; this module maps the RFC provider verbs
(``load`` / ``compare_and_put``) onto the NoKV Python SDK and nothing else.
The canonical byte encoding is imported from the production head codec so the
adapter cannot fork the digest/parity basis.

Failure classification is by exception class ONLY. Since NoKV 0.11.0 (the
pinned RFC baseline) the SDK raises ``FileNotFoundError`` for a missing path
and ``FileExistsError`` for a create-only collision; every other RPC,
transport, routing, or publication failure is a ``RuntimeError``. Error prose
is never a channel: real non-missing failures carry messages such as
``invalid root route: root placement does not exist`` and ``logical shard ...
was not found``, so any message-token fallback misclassifies an outage as an
uninitialized goal - the one confusion RFC section 6.2 forbids (``missing``
must never collapse into ``unavailable``). Pre-0.11 SDKs cannot route the
post-#465 control plane at all and are outside the supported baseline.
"""

from __future__ import annotations

import json
import uuid

from loopx.control_plane.coordination.head import (
    HeadValidationError,
    canonical_head_bytes,
)


class ProviderProtocolError(RuntimeError):
    """Persisted bytes or a provider result violated the reviewed contract."""


class ProviderUnavailableError(RuntimeError):
    """The storage plane could not serve the request; nothing is proven.

    Raised on read paths, where the RFC verbs offer no typed channel. It is
    categorically different from ``(None, 0)``: missing is a proven absence
    that authorizes bootstrap-create, while unavailable means the head's
    existence is unknown and every decision must fail closed.
    """


def _generation_from(metadata) -> int:
    try:
        return int(metadata["generation"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderProtocolError(
            f"provider result omitted a usable generation: {exc}"
        ) from exc


class NoKVCoordinationProvider:
    """Map one goal's canonical head bytes to a NoKV generation CAS.

    ``load`` returns ``(head | None, provider_generation)`` where ``None``
    is proven absence (``FileNotFoundError`` from the SDK) and any other
    client failure raises the typed :class:`ProviderUnavailableError`.
    ``compare_and_put`` reports the four RFC verbs: an outage before the
    publish is typed ``failed`` (provably no write), and a publish that
    raises is ``ambiguous`` - human error text is never parsed as commit
    proof; the authority reloads and trusts only its atomically stored
    receipt index.
    """

    _CLIENT_ERRORS = (RuntimeError, OSError)

    def __init__(self, client, workbench: str, goal_id: str):
        self.client = client
        self.workbench = workbench
        self.goal_id = goal_id
        self.head_path = f"goals/{goal_id}/coordination-head.json"

    def load(self):
        """Return ``(aggregate | None, provider_generation)``."""
        try:
            result = self.client.read(self.workbench, self.head_path)
        except FileNotFoundError:
            return None, 0
        except self._CLIENT_ERRORS as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        try:
            aggregate = json.loads(bytes(result["bytes"]))
        except ValueError as exc:
            raise ProviderProtocolError(
                f"coordination head is not valid JSON: {exc}"
            ) from exc
        if not isinstance(aggregate, dict):
            raise ProviderProtocolError("coordination head must be an object")
        return aggregate, _generation_from(result["metadata"])

    def _generation(self) -> int:
        try:
            metadata = self.client.stat(self.workbench, self.head_path)
        except FileNotFoundError:
            return 0
        except self._CLIENT_ERRORS as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        return _generation_from(metadata)

    def compare_and_put(
        self,
        expected_provider_generation: int,
        aggregate: dict,
    ) -> dict:
        """Serialize and conditionally store an opaque aggregate."""
        try:
            current = self._generation()
        except ProviderUnavailableError as exc:
            # No publish was attempted, so this failure proves no write.
            return {"result": "failed", "error": str(exc)}
        if current != expected_provider_generation:
            return {"result": "conflict", "current_provider_generation": current}
        try:
            payload = canonical_head_bytes(aggregate)
        except HeadValidationError as exc:
            # Serialization runs before any publish, so this failure proves
            # no write; it surfaces as the typed verb exactly like the file
            # provider, never as an unclassified exception through the seam.
            return {"result": "failed", "error": str(exc)}
        try:
            result = self.client.publish_bytes(
                self.workbench,
                self.head_path,
                payload,
                content_type="application/json",
                expected_generation=(
                    None if expected_provider_generation == 0
                    else expected_provider_generation
                ),
                operation_id=uuid.uuid4().hex,
                artifact_revision_id=uuid.uuid4().hex,
            )
        except self._CLIENT_ERRORS:
            # Do not parse human error text as commit proof: a create-only
            # collision (``FileExistsError``), a generation mismatch, or a lost
            # response all reload; the authority trusts only its atomically
            # stored receipt index.
            return {"result": "ambiguous"}
        try:
            applied_generation = int(result["generation"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderProtocolError(
                f"publish result omitted a usable generation: {exc}"
            ) from exc
        return {
            "result": "applied",
            "provider_generation": applied_generation,
        }
