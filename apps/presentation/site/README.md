# LoopX Public Website

This directory owns the React/Vite, public-safe
[LoopX homepage](https://huangruiteng.github.io/loopx/) published at the root
of the GitHub Pages site. The frontstage exporter builds this application into
the Pages root and publishes the compiled dashboard at `/frontstage/`.

Vite's base path is supplied by the exporter so links and assets work both at
the repository Pages base (`/loopx/`) and in root-base local previews.

The language switch keeps English as the default and provides a public-safe
Chinese locale. `?lang=zh` is the shareable Chinese entry.

The first-run CTA opens one setup dialog with a recommended Agent path and a
manual Shell path. The Agent option copies the localized, public-safe setup
contract; the Shell option copies the commands shown in the terminal section.
The `See in action` CTA scrolls to the public evidence showcase and restarts the
Issue Fix replay.

The homepage control-plane diagrams are synthetic UI. Finite, tabbed terminal
replays summarize two public README trajectories; they are curated projections,
not raw session logs. The full-screen viewer bundles only the two explicit
`docs/assets/long-running-loop-*-trajectory.png` files. The site must not consume
live LoopX state, local status feeds, private registries, raw logs, or write
APIs.
