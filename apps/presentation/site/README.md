# LoopX Public Website

This directory owns the static, public-safe
[LoopX homepage](https://huangruiteng.github.io/loopx/) published at the root
of the GitHub Pages site. The dashboard exporter copies the compiled React
application to `/frontstage/`, then writes this homepage to the Pages root.

`__LOOPX_BASE__` is replaced by the exporter so links and assets work both at
the repository Pages base (`/loopx/`) and in root-base local previews.

The language switch keeps English as the canonical source markup and default
entry, then applies a public-safe Chinese locale in the browser. `?lang=zh`
provides a shareable Chinese entry.

The first-run CTA is agent-first. It copies the localized, public-safe setup
contract from `home.js` so the current agent can install or repair LoopX,
identify its exact host, preserve existing project state, and complete the
host-specific activation packet. The terminal block lower on the page remains
the manual fallback; it does not claim that project connection alone activates
a host loop.

The homepage control-plane diagrams are synthetic UI. Finite, tabbed terminal
replays summarize two public README trajectories; they are curated projections,
not raw session logs. The full-screen viewer loads only the two explicitly
copied `docs/assets/long-running-loop-*-trajectory.png` files. The site must not
consume live LoopX state, local status feeds, private registries, raw logs, or
write APIs.
