# content_ops_queue_projection_v0

Status: read-only managed queue projection v0.

`content_ops_queue_projection_v0` is the queue surface for caller-owned
`content_ops_item_v0` records. It is not a publisher and never stores draft
bodies. The order of the input item files is the priority order.

## Boundary

The projection derives from validated item records only:

- stable `item_id`, `item_kind`, channel, state, revision, and opaque
  `content_ref`;
- state counts and terminal count;
- the first actionable non-terminal item as `next_action`;
- no draft bodies, credentials, browser state, media, private source maps, or
  local paths.

## CLI

Project a caller-owned queue:

```bash
loopx content-ops queue-status \
  --item-json items/launch-post-v1.json \
  --item-json items/community-recap-v1.json \
  --queue-id loopx-x-operations \
  --generated-at 2026-08-10T02:00:00+08:00 \
  --format json
```

The command reports `external_reads_performed=false`,
`external_writes_performed=false`, and `autopublish_allowed=false`.

## Truth Contract

`queue-status` is a read-only projection. Approval, delivery, and readback must
still go through the item lifecycle and exact owner-authorization records; the
queue surface itself has no publish authority.
