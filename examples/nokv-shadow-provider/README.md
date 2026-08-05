# NoKV shadow-provider reference implementation

Reference implementation of the LoopX storage-provider contract proposed in
[RFC: shared-goal authority and pluggable state provider v0](../../docs/architecture/rfcs/shared-goal-authority-state-provider-v0.md):

```
load() -> (envelope_bytes, revision)
compare_and_put(expected_revision, command_id, envelope_bytes)
    -> applied(new_revision) | conflict(current_revision) | already_applied
```

`revision` maps to NoKV's per-path `generation` on a single per-goal head
document. One goal is pinned to one root/shard, so every command for a goal
is serialized by a single writer. The adapter encodes the four contract
disciplines from RFC §5: never delete the head document, byte-deterministic
envelopes, deterministic operation-id derivation from `command_id`, and
conflict classification (already-applied proof / bounded contention retry /
unavailable vs. conflict).

## Files

- `provider.py` (~200 lines): the adapter. `NoKVShadowProvider.load()` and
  `.compare_and_put()` plus a `sample_envelope()` helper producing the
  `loopx_command_v0` claim_work envelope from the RFC.
- `probes.py`: the acceptance probes (P1-P6) whose measured results are
  reported in the
  [e2e evidence document](../../docs/architecture/rfcs/shared-goal-authority-state-provider-v0-evidence.zh-CN.md).

## Requirements

- A running NoKV stack: `etcd`, an S3-compatible object store, and one
  `nokv serve` shard owner (all can bind 127.0.0.1 on a single machine).
- The NoKV Python SDK built from the NoKV repository
  (`pip install <nokv-repo>/crates/nokv-python`, maturin backend).

## Quickstart

```bash
# 1) etcd (single node, local)
etcd --listen-client-urls http://127.0.0.1:2379 \
     --advertise-client-urls http://127.0.0.1:2379

# 2) any S3-compatible store on 127.0.0.1:9000, then create the bucket
aws --endpoint-url http://127.0.0.1:9000 s3 mb s3://nokv-loopx-e2e

# 3) provision + serve (all ids are 32-char lowercase hex)
nokv --root-id <ROOT_ID> --etcd-endpoint http://127.0.0.1:2379 \
     --etcd-key-prefix /nokv/loopx provision <LOGICAL_SHARD_ID>
nokv --root-id <ROOT_ID> --etcd-endpoint http://127.0.0.1:2379 \
     --etcd-key-prefix /nokv/loopx \
     --object-bucket nokv-loopx-e2e --object-endpoint http://127.0.0.1:9000 \
     --object-access-key-id <KEY> --object-secret-access-key <SECRET> \
     --bind 127.0.0.1:7801 --advertise-endpoint 127.0.0.1:7801 \
     --node-id n1 --metadata-create <METADATA_DIR> serve

# 4) probes
export NOKV_ROOT_ID=<ROOT_ID> NOKV_ETCD_PREFIX=/nokv/loopx \
       NOKV_S3_KEY=<KEY> NOKV_S3_SECRET=<SECRET>
python probes.py setup
python probes.py p1   # single claim -> applied + receipt
python probes.py p2   # 8-way concurrent claim x 20 rounds -> exactly one applied
python probes.py p3b  # crash-retry with same command_id -> already_applied
python probes.py p5   # 100 cycles -> latency distribution
python probes.py p6   # two goals in one root -> independent revisions
```

Probes emit JSON lines to stdout as raw evidence. Measured results, the full
environment recipe, and the known caveats are in the evidence document above.
