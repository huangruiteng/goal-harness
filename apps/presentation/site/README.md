# LoopX Public Website

This directory owns the React/Vite, public-safe
[LoopX homepage](https://huangruiteng.github.io/loopx/) published at the root
of the GitHub Pages site. The frontstage exporter builds this application into
the Pages root and publishes the compiled dashboard at `/frontstage/`.

Vite's base path is supplied by the exporter so links and assets work both at
the repository Pages base (`/loopx/`) and in root-base local previews.

The language switch keeps English as the default and provides a public-safe
Chinese locale. `?lang=zh` is the shareable Chinese entry.

The Blog is a static editorial section under `public/blog/`. `/blog/` and its
articles default to English; `/blog/zh/` contains the paired Chinese editions.
Each language has a direct URL, a matching language switch, canonical and
alternate-language metadata, and the complete article in HTML. Reading and
navigation work without JavaScript. Vite copies these pages into both the local
build and the existing Pages export; no separate hosting or content service is
needed. Relative navigation supports both root and repository base paths.

Edit the paired HTML editions together, including their index summaries and
metadata. Preserve matching section anchors and public source attribution.
Keep source-document exports, private references, and unreviewed media outside
the public tree. Follow `docs/development/design.md` and obtain first-screen
review before changing the Blog or its homepage entry.

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
