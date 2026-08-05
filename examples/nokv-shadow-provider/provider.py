"""Reference LoopX storage-provider adapter over the NoKV Python SDK.

Maps LoopX provider contract:
  load() -> (envelope_doc | None, revision:int)
  compare_and_put(expected_revision, command_id, envelope) -> receipt dict

revision <-> NoKV per-path generation on a single per-goal head path.
expected_revision == 0 means "head must not exist" (CreateOnly).

Idempotency: operation_id / artifact_revision_id deterministically derived
from command_id (16-byte hex each), so a crash/retry with the same command_id
replays server-side (replayed=True) instead of double-applying.

already_applied detection on CAS conflict: re-read head; if
head.command_id == submitted command_id => already_applied, else typed
conflict carrying the current revision.
"""

import hashlib
import json
import time
import uuid


def _derive_id(tag: str, command_id: str) -> str:
    return hashlib.sha256(f"{tag}:{command_id}".encode()).hexdigest()[:32]


class NoKVShadowProvider:
    def __init__(self, client, workbench: str, goal_id: str):
        self.client = client
        self.workbench = workbench
        self.head_path = f"goals/{goal_id}/head.json"

    # ---- load ----------------------------------------------------------
    # Transient read races under head churn: client.read() resolves head
    # metadata (logical_size of revision R) then range-reads; a concurrent
    # replace with a smaller body makes the server reject the stale range
    # ("requested byte range exceeds the artifact logical size").  The SDK
    # only auto-retries fence changes, so the adapter retries here.
    _TRANSIENT = ("exceeds the artifact logical size", "fence changed",
                  "retry budget", "read fence")

    def load(self, _retries=10):
        """Return (doc | None, revision). revision==0 means head absent."""
        last = None
        for attempt in range(_retries):
            try:
                result = self.client.read(self.workbench, self.head_path)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if ("not found" in msg or "does not exist" in msg
                        or "no such path" in msg):
                    return None, 0
                if any(t in msg for t in self._TRANSIENT):
                    last = exc
                    time.sleep(0.01 * (attempt + 1))
                    continue
                raise
            doc = json.loads(bytes(result["bytes"]))
            revision = int(result["metadata"]["generation"])
            return doc, revision
        raise last

    def stat_revision(self):
        try:
            meta = self.client.stat(self.workbench, self.head_path)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "not found" in msg or "does not exist" in msg or "no such path" in msg:
                return 0
            raise
        return int(meta["generation"])

    # ---- compare_and_put ----------------------------------------------
    def compare_and_put(self, expected_revision: int, command_id: str, envelope: dict):
        assert envelope.get("schema_version") == "loopx_command_v0"
        now = time.time()
        ttl = int(envelope["command"].get("lease_ttl_seconds", 600))
        lease_id = "lease-" + _derive_id("lease", command_id)[:16]
        doc = {
            "schema_version": "loopx_authority_head_v0",
            "command_id": command_id,
            "idempotency_key": envelope.get("idempotency_key"),
            "envelope": envelope,
            "applied_at_unix": now,
            "lease": {
                "lease_id": lease_id,
                "holder": envelope.get("actor"),
                "todo_id": envelope["command"].get("todo_id"),
                "expires_at_unix": now + ttl,
            },
        }
        expected_generation = None if expected_revision == 0 else int(expected_revision)
        # Owner-side optimistic-concurrency contention ("metadata write
        # read-version mismatch", stale operation tokens) is retryable and is
        # NOT a CAS verdict; only path-generation mismatch / already-exists is.
        contention = ("read-version mismatch", "token state digest is stale",
                      "invalid publish transition", "exhausted")
        res = None
        last_exc = None
        applied_proof = False  # op id already succeeded server-side
        salt = 0  # salt 0 == canonical ids: preserves crash-replay of a
        #           completed publish; a burned (aborted) id bumps the salt.
        for attempt in range(8):
            tag = "" if salt == 0 else f"#{salt}"
            try:
                res = self.client.publish_bytes(
                    self.workbench,
                    self.head_path,
                    json.dumps(doc, sort_keys=True).encode(),
                    content_type="application/json",
                    expected_generation=expected_generation,
                    operation_id=_derive_id("op" + tag, command_id),
                    artifact_revision_id=_derive_id("rev" + tag, command_id),
                )
                break
            except RuntimeError as exc:
                last_exc = exc
                msg = str(exc).lower()
                if ("reused with different immutable inputs" in msg
                        or "already succeeded" in msg):
                    # The canonical operation id already completed with the
                    # original bytes: the command WAS applied. Never bump the
                    # salt here (that would double-apply). Classify below.
                    applied_proof = True
                    break
                if ("did not remain in running state" in msg
                        or "revisionalreadyexists" in msg
                        or "revision identity collision" in msg
                        or "revision already exists" in msg):
                    # operation/revision id burned by an aborted attempt
                    salt += 1
                    continue
                if "generation mismatch" in msg or "already exists" in msg:
                    break  # definitive CAS verdict
                if any(t in msg for t in contention):
                    time.sleep(0.02 * (attempt + 1))
                    continue
                raise
        if res is None:
            # Definitive CAS conflict, or contention retries exhausted.
            # Classify by re-reading head; wait briefly for the winner's
            # commit to become visible so the caller learns the new revision.
            deadline = time.time() + 2.0
            while True:
                cur_doc, cur_rev = self.load()
                if cur_rev != expected_revision or time.time() >= deadline:
                    break
                time.sleep(0.02)
            if cur_doc is not None and cur_doc.get("command_id") == command_id:
                return {
                    "result": "already_applied",
                    "authority_revision": cur_rev,
                    "lease_id": cur_doc["lease"]["lease_id"],
                    "epoch": cur_rev,
                    "expires_at_unix": cur_doc["lease"]["expires_at_unix"],
                    "raw_error": str(last_exc),
                }
            if applied_proof:
                # Applied historically, but head has since moved past it.
                return {
                    "result": "already_applied",
                    "superseded": True,
                    "current_revision": cur_rev,
                    "raw_error": str(last_exc),
                }
            if cur_rev == expected_revision:
                # Head never advanced: no CAS verdict was reached (e.g. a
                # publication wedged in Finalizing). Retryable, NOT a conflict.
                return {
                    "result": "unavailable",
                    "current_revision": cur_rev,
                    "expected_revision": expected_revision,
                    "raw_error": str(last_exc),
                }
            return {
                "result": "conflict",
                "current_revision": cur_rev,
                "expected_revision": expected_revision,
                "raw_error": str(last_exc),
            }
        new_rev = int(res["generation"])
        return {
            "result": "applied",
            "authority_revision": new_rev,
            "lease_id": lease_id,
            "epoch": new_rev,
            "expires_at_unix": doc["lease"]["expires_at_unix"],
            "replayed": bool(res.get("replayed")),
            "commit_version": res.get("commit_version"),
            "body_digest": res.get("body_digest"),
        }


def sample_envelope(command_id=None, agent_id="agent-a", device_id="dev-laptop",
                    goal_id="ark-agent-loop-shared", expected_revision=0,
                    todo_id="todo-0042"):
    return {
        "schema_version": "loopx_command_v0",
        "command_id": command_id or str(uuid.uuid4()),
        "idempotency_key": "idem-" + (command_id or "x")[:8],
        "actor": {"agent_id": agent_id, "device_id": device_id},
        "goal_id": goal_id,
        "expected_revision": expected_revision,
        "command": {
            "type": "claim_work",
            "todo_id": todo_id,
            "expected_todo_revision": 7,
            "lease_ttl_seconds": 600,
        },
    }
