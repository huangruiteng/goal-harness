# Stage 2A NoKV AuthorityStore candidate qualification (TEST ONLY)

This directory contains an explicit, write-producing single-node conformance
probe for the Stage 2A `NoKVAuthorityStore` candidate. It is **TEST ONLY**.
LoopX does not select NoKV by importing this code, and a successful run does
not connect a runtime shadow, run a multi-Agent canary, or flip an authority
source.

The integration priority remains:

1. the native, full NoKV CLI as the primary operator and production surface;
2. the NoKV Python SDK as the secondary programmable surface; and
3. optional sidecars only as adapters around those surfaces, never as the main
   authority API.

This probe intentionally exercises the current Python SDK bridge because it is
the available raw byte-CAS seam. It always starts this checkout's reviewed
`NoKVJsonLinesTransport` and `nokv_jsonl_helper.py`; it has no fake, skip, or
"unverified but successful" CLI path. The helper admits exactly NoKV SDK
`0.11.0` / Python API `1`, and the successful report repeats both values.

## What it proves

Against one **already existing** NoKV workbench, the probe starts three
independent helper processes and verifies:

- the selected tenant/goal path is initially absent and can be created;
- the stored path generation advances from 1 to 2 under exact generation CAS;
- after the generation-2 CAS lands, an injected response loss is reconciled
  from the durable authority envelope and operation receipt rather than from
  the lower-layer response;
- two writes released together against generation 2 produce exactly one
  generation-3 winner and one typed conflict;
- the losing operation does not acquire a durable receipt; and
- a third, freshly opened transport reads the winning envelope, its complete
  three-entry history, the response-lost operation receipt, and the retained
  winner receipt.

If the SDK, helper, workbench, backend, CAS, or independent readback cannot be
proved, the process exits nonzero. The normal test suite uses deterministic
fakes only to test this sequence and does **not** count as live evidence.

The probe does not prove runtime shadow parity, a multi-Agent canary, authority
promotion, HA, failover, restart recovery, capacity, or performance. It also
does not create a workbench. A green run is Stage 2A single-node storage
conformance evidence only.

## Inputs

Use a current NoKV Python environment. Keep the client configuration in an
ignored local file; do not commit credentials. Static routing is valid for a
single-node NoKV deployment—etcd is not required by this probe. The following
shape is illustrative:

```json
{
  "root_id": "00000000000000000000000000000000",
  "routing": {
    "kind": "static",
    "endpoint": "127.0.0.1:7412",
    "logical_shard_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "object_namespace_id": "cccccccccccccccccccccccccccccccc",
    "placement_generation": 1,
    "owner_epoch": 1
  },
  "object_store": {
    "kind": "s3",
    "bucket": "qualification-bucket",
    "region": "us-east-1",
    "root": "/loopx-qualification",
    "endpoint": "http://127.0.0.1:9000",
    "access_key_id": "set-in-your-ignored-local-file",
    "secret_access_key": "set-in-your-ignored-local-file",
    "virtual_host_style": false,
    "skip_signature": false
  }
}
```

Configuration objects are exact-key contracts. An unknown top-level, routing,
or object-store key fails before an SDK routing config, object-store config, or
client is constructed. In particular, a misspelled explicit credential cannot
silently fall through to NoKV's ambient provider chain. Intentionally omitted
optional S3 credential fields retain the NoKV SDK's normal behavior.

Pass only the absolute path to the Python executable that resolves the qualified
NoKV SDK. The probe itself fixes the second and only other argv entry to the
reviewed helper in this checkout; callers cannot supply a wrapper argument or
alternate helper path:

```text
/path/to/nokv-python-environment/bin/python
```

Choose a fresh tenant/goal pair for every run. The probe refuses to overwrite
an existing authority envelope and deliberately leaves its three-generation
test envelope behind for inspection. Use a disposable qualification namespace
or remove it later with the native NoKV CLI according to that environment's
retention policy.

## Run

From the LoopX repository root:

```bash
node --no-warnings --experimental-strip-types \
  examples/nokv-authority-store/live-qualification.ts \
  --execute-live \
  --config-json /path/to/ignored/nokv-client.json \
  --python-executable /path/to/nokv-python-environment/bin/python \
  --tenant-id qualification-tenant-20260902 \
  --goal-id qualification-goal-20260902-01 \
  --workbench existing-qualification-workbench
```

`--execute-live` is mandatory and is checked before any helper starts. Exit 0
means every listed live check passed. Any unavailable, failed, ambiguous,
unfenced, pre-existing, or unreadable state exits nonzero with a compact JSON
reason; provider stderr, endpoints, credentials, and raw SDK errors are not
copied into that result. A successful JSON report includes
`"qualification_scope":"stage_2a_single_node_store_conformance"`,
`"nokv_sdk_version":"0.11.0"`, and `"nokv_api_version":1`; those fields are an
exact Stage 2A/helper-admission claim, not runtime-shadow, canary, HA, or
production-readiness evidence.
