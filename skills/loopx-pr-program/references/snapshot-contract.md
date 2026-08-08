# PR Program Snapshot Contract

Use `loopx_pr_program_snapshot_v0` as the provider-neutral boundary between
source acquisition and LoopX program reconciliation. Keep source-specific
commands and credentials outside the snapshot producer committed to LoopX.

## Shape

```json
{
  "schema_version": "loopx_pr_program_snapshot_v0",
  "program_id": "runtime-reliability",
  "generated_at": "2026-08-06T10:00:00Z",
  "result_completeness": {
    "complete": true,
    "scope": {
      "repositories": ["example/runtime"],
      "states": ["open"],
      "authors": [],
      "time_window": {"since": null, "until": null}
    }
  },
  "requirements": [
    {
      "id": "runtime-parameters",
      "title": "Expose runtime quality and latency controls",
      "priority": "P0",
      "coverage": "partial"
    }
  ],
  "change_requests": [
    {
      "ref": "example/runtime#42",
      "repository": "example/runtime",
      "number": 42,
      "url": "https://example.invalid/example/runtime/changes/42",
      "title": "feat(runtime): expose quality control",
      "state": "open",
      "draft": true,
      "target_branch": "main",
      "head_sha": "0123456789abcdef",
      "updated_at": "2026-08-06T09:55:00Z",
      "checks": "passed",
      "review": "pending",
      "work_item": "action_required",
      "theme": "runtime parameters",
      "priority": "P0",
      "requirement_ids": ["runtime-parameters"],
      "depends_on": [],
      "supersedes": [],
      "description_digest": "sha256:public-safe-digest",
      "review_digest": "sha256:public-safe-digest"
    }
  ]
}
```

## Required Invariants

- `program_id`, `generated_at`, `result_completeness`, `requirements`, and
  `change_requests` must be present.
- `ref` is the stable unique key. Prefer `repository#number`; do not use title.
- `result_completeness.scope` is a structured inventory identity. It must name
  repository, state, author, and time-window filters explicitly; arrays are
  unordered filter sets. The delta helper normalizes and hashes the complete
  object, including any additional provider-neutral filters.
- `result_completeness.complete` controls removal semantics only when the
  previous and current scope fingerprints match. Missing rows are removals only
  when the current inventory is complete for the same scope. Incomplete or
  scope-mismatched snapshots must not replace the durable baseline or monitor
  result hash.
- `updated_at` is observational. It must not trigger a material transition by
  itself.
- `description_digest` and `review_digest` may prove content movement without
  storing raw private text.
- `requirements[].priority` is the product priority. A change request may have a
  lower effective priority only when the owner explicitly records that choice.
- `coverage` is `none`, `partial`, or `complete`. Do not infer `complete` from a
  merged neighbor.

## Integration-Branch Composition

The snapshot is the remote lifecycle and requirement view; it is not an
integration-branch plan. When the program uses a local integration candidate,
map only explicitly selected change requests to the separate ignored
`loopx_integration_branch_plan_v0` state.

Before each reconcile, prove that the selected local source ref resolves to the
snapshot row's `head_sha`. Feed the resulting
`loopx_integration_branch_status_v0` readback into the grouped program monitor
as additional evidence. Keep source ref names and sync receipts in ignored
project-local state; do not add them to a public roadmap merely to make this
composition work.

Normalize lifecycle values as follows:

| Field | Values |
| --- | --- |
| `state` | `open`, `merged`, `closed`, `unknown` |
| `checks` | `passed`, `failed`, `pending`, `unknown` |
| `review` | `pending`, `approved`, `changes_requested`, `unknown` |
| `work_item` | `passed`, `failed`, `action_required`, `unknown` |
| `priority` | `P0`, `P1`, `P2`, or `unclassified` |

## Material Fields

The delta helper considers these fields material:

- `title`, `state`, `draft`, `target_branch`, and `head_sha`;
- `checks`, `review`, and `work_item`;
- `theme`, `priority`, `requirement_ids`, `depends_on`, and `supersedes`;
- `description_digest` and `review_digest`;
- requirement title, priority, and coverage.

Treat additions and complete-snapshot removals as material. Treat
`generated_at` and timestamp-only `updated_at` changes as observation-only.

## Privacy Checklist

Before committing any fixture or example derived from a real program, verify:

- repository names, URLs, change request titles, people, and comments are
  public;
- no credential, token, private executable name, internal hostname, local path,
  or document id remains;
- raw comments and descriptions are replaced with public-safe digests unless
  their public text is intentionally part of the fixture;
- the fixture is minimal and proves a reusable semantic invariant.
