# Content-Ops Layout v0

`content_ops_layout_*_v0` makes content presentation a reviewable LoopX
contract. It separates three owners:

- LoopX core owns built-in templates, typed page roles, deterministic
  compactness thresholds, and acceptance results.
- A writing or platform adapter owns the copy, page selection, narrative
  structure, author voice, and rendering.
- A renderer owns pixels and emits a compact measurement packet; LoopX does not
  add an image-processing dependency or ingest draft bodies.

This is a machine-enforced acceptance check, not optional prose guidance.

## Template library

```bash
loopx content-ops template-list --format json
loopx content-ops template-show \
  --template-id light-serif-longform \
  --format json
```

The built-in `content_ops_layout_template_catalog_v0` currently includes:

- `light-serif-longform` for dense analytical storytelling;
- `monochrome-editorial` for high-contrast technical commentary;
- `product-brief` for problem/mechanism/boundary summaries;
- `control-plane-hybrid` for prose plus state, gate, and evidence artifacts.

Templates define canvas size, safe area, density limits, page archetypes, and
portable style tokens. They do not contain project names, private paths, draft
bodies, or provider credentials.

## Typed plan

Build a plan before rendering:

```bash
loopx content-ops layout-plan \
  --item-id plugin-scaling-note \
  --template-id light-serif-longform \
  --page p01:cover:source-system \
  --page p02:argument:source-system \
  --page p03:evidence:source-system \
  --page p04:closing:creator-system \
  --required-role cover \
  --required-role argument \
  --required-role evidence \
  --required-role closing \
  --closing-role closing \
  --generated-at 2026-08-15T12:00:00+08:00 \
  --format json
```

Roles are typed as `cover`, `argument`, `mechanism`, `evidence`, `boundary`,
`closing`, or `cta`. Project-specific narrative obligations—such as ending in
the creator's voice or bridging from one named subject to another—remain in the
writing adapter or item-local review plan. LoopX does not universalize them or
infer them from prose substrings.

## Renderer measurement

The renderer emits `content_ops_layout_measurement_v0`:

```json
{
  "schema_version": "content_ops_layout_measurement_v0",
  "plan_id": "layout:plugin-scaling-note:light-serif-longform",
  "template_id": "light-serif-longform",
  "pages": [
    {
      "page_id": "p01",
      "asset_ref": "images/p01.jpg",
      "canvas": {"width": 1440, "height": 1920},
      "meaningful_content_bounds": {"top": 154, "bottom": 1364},
      "checks": {
        "overflow": false,
        "collision": false,
        "single_character_line": false
      }
    }
  ]
}
```

`asset_ref` must be a relative public-safe reference. Meaningful bounds exclude
decorative rules, page numbers, and footers so they cannot make a sparse page
look full.

## Acceptance

```bash
loopx content-ops layout-check \
  --plan-json layout-plan.json \
  --measurement-json layout-measurement.json \
  --format json
```

`content_ops_layout_check_packet_v0` returns `pass` only when:

- measured page ids exactly match the plan;
- all required roles are present and the last page has the planned closing role;
- canvas and density satisfy the selected template and role;
- overflow, collision, and single-character-line checks are explicitly false;
- every renderer safety check is explicitly satisfied.

The packet always keeps `autopublish_allowed=false`. Layout acceptance never
grants provider access, publishing authority, or approval for the content body.
