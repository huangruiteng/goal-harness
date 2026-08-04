# LoopX Public Website

This directory owns the static, public-safe homepage published at the root of
the LoopX GitHub Pages site. The dashboard exporter copies the compiled React
application to `/frontstage/`, then writes this homepage to the Pages root.

`__LOOPX_BASE__` is replaced by the exporter so links and assets work both at
the repository Pages base (`/loopx/`) and in root-base local previews.

The language switch keeps English as the canonical source markup and default
entry, then applies a public-safe Chinese locale in the browser. `?lang=zh`
provides a shareable Chinese entry.

The homepage control-plane diagrams are synthetic UI. The curated evidence maps
summarize two public README trajectories, and the full-screen viewer loads only
the two explicitly copied `docs/assets/long-running-loop-*-trajectory.png`
files. The site must not consume live LoopX state, local status feeds, private
registries, raw logs, or write APIs.
