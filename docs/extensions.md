# Extensions And Capabilities

Capabilities and extensions are independent dimensions in LoopX:

- a **capability** describes what LoopX can do and the product contract exposed
  to callers;
- an **extension** is a delivery unit that can provide one or more capabilities
  and has its own installation, enablement, disablement, and upgrade lifecycle.

Built-in capabilities and extension-provided capabilities share one registry.
Implementation directories do not become capabilities merely because they live
under `loopx/capabilities/`; registration is explicit.

```text
LoopX Core
|-- capability contracts
|-- built-in capability registrations
`-- extension runtime
      |-- extension A -- provides capabilities
      |-- extension B -- provides capabilities
      `-- extension C -- provides capabilities
```

## Registration Model

Every registered capability declares three provider-facing fields:

- `origin`: `builtin` or `extension`;
- `visibility`: `public` or `internal`;
- `provider_id`: `loopx-core` or the extension manifest id.

The built-in catalog remains the default source. Explicitly enabled extension
manifests are validated and appended in caller order. Duplicate capability or
provider ids fail closed. Internal registrations remain available to the
registry but are omitted from the public catalog.

The initial runtime does not scan arbitrary directories and does not import
extension Python code while reading the catalog. A caller enables a manifest
for one catalog operation explicitly:

```bash
loopx capability list \
  --extension-manifest /path/to/extension.toml \
  --format json

loopx capability show lark-kanban \
  --extension-manifest /path/to/extension.toml \
  --format json
```

This explicit read path establishes the registration contract without
prematurely defining an installer, package repository, or global activation
store. Those lifecycle surfaces can later provide the same validated manifest
paths to the registry.

## Manifest Contract

An extension manifest is declarative TOML. `[[provides]]` records carry enough
metadata to enter the capability catalog without loading provider code.
The v0 runtime exposes integer extension API version `1` and accepts bounded
integer constraints such as `>=1,<2`; incompatible manifests fail closed.

```toml
schema_version = "loopx_extension_manifest_v0"
id = "loopx-lark"
version = "1.0.0"
requires_loopx_api = ">=1,<2"
permissions = ["read_status", "read_todos", "external_write"]

[[provides]]
id = "lark-kanban"
kind = "projection_sink"
title = "Lark Kanban projection"
status = "active"
visibility = "public"
real_world_anchor = "operator-facing Lark Base projection"
user_value = "Project public-safe LoopX status and todo rows into Lark."
entry_command = "loopx lark-kanban sync"
next_real_step = "Validate one explicitly enabled owner-approved sink."
```

`permissions` are declared provider metadata in this stage. Declaring a
permission does not grant it: existing LoopX goal boundaries, user gates, and
external-write authorization still decide whether an operation may execute.

## Scope Boundaries

This first stage intentionally does not:

- rename or move existing capability implementation directories;
- infer capabilities from Python packages;
- install, enable, disable, or upgrade extension packages;
- import an extension entrypoint during catalog discovery;
- let manifest permissions bypass LoopX control-plane authority.

These omissions keep the registry useful now while leaving package and
lifecycle policy to a later, evidence-backed call site.
