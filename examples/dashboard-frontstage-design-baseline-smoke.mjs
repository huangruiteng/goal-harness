import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function includes(source, snippet, label) {
  assert(source.includes(snippet), `missing ${label}: ${snippet}`);
}

function excludes(source, snippet, label) {
  assert(!source.includes(snippet), `unexpected ${label}: ${snippet}`);
}

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function readRepoFile(path) {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

const productDoc = readRepoFile("docs/product/surfaces/frontstage-dashboard-interaction-baseline.md");
const surfaceReadme = readRepoFile("docs/product/surfaces/README.md");
const dashboardReadme = readRepoFile("apps/presentation/dashboard/README.md");
const frontstageSource = readRepoFile("apps/presentation/dashboard/src/views/frontstage-page.tsx");
const deprecatedOpsSource = readRepoFile("apps/presentation/dashboard/src/views/deprecated/frontstage-ops-page.tsx");
const deprecatedOpsStyles = readRepoFile("apps/presentation/dashboard/src/views/deprecated/frontstage-ops.css");
const stylesSource = readRepoFile("apps/presentation/dashboard/src/styles.css");
const browserSmoke = readRepoFile("examples/dashboard-frontstage-browser-smoke.mjs");
const packageSource = readRepoFile("apps/presentation/dashboard/package.json");

includes(productDoc, "## Surface Split", "surface split section");
includes(productDoc, "Showcase/homepage", "showcase surface row");
includes(productDoc, "Legacy Ops diagnostics", "deprecated diagnostics surface row");
includes(productDoc, "Multica-style agent workspace direction", "Multica-style product benchmark");
includes(productDoc, "React, Vite, TypeScript, and TanStack Router", "frontend stack baseline");
includes(productDoc, "TanStack Table", "table stack baseline");
includes(productDoc, "Tailwind plus owned shadcn/Base UI-like primitives", "owned component baseline");
includes(productDoc, "lucide-react", "icon baseline");
includes(productDoc, "Zod", "schema boundary baseline");
includes(productDoc, "showcase surface can be fancy", "showcase motion allowance");
includes(productDoc, "working console, not a landing page", "ops workspace rule");
includes(productDoc, "frontstage-ops-workspace-shell", "ops shell anchor");
includes(productDoc, "frontstage-ops-command-strip", "ops command strip anchor");
includes(productDoc, "## Frontstage/Status Sufficiency Check", "frontstage status sufficiency section");
includes(productDoc, "Todo-flow review", "todo-flow sufficiency check");
includes(productDoc, "Human-gate animation", "human-gate animation sufficiency check");
includes(productDoc, "Multi-lane timeline", "multi-lane timeline sufficiency check");
includes(productDoc, "long-horizon-self-iteration-rollout.public.json", "long-horizon rollout fixture anchor");
includes(productDoc, "long-horizon-self-iteration-rollout-fixture-smoke.py", "fixture smoke anchor");
includes(productDoc, "npm run smoke:frontstage-browser", "visual acceptance anchor");
includes(productDoc, "npm run smoke:frontstage-design-baseline", "design smoke anchor");

includes(surfaceReadme, "frontstage-dashboard-interaction-baseline.md", "surface README link");
includes(dashboardReadme, "frontstage-dashboard-interaction-baseline.md", "dashboard README link");
includes(dashboardReadme, "showcase mode is", "dashboard README surface split");
includes(dashboardReadme, "/deprecated/frontstage/ops", "dashboard README deprecated diagnostics route");

includes(frontstageSource, 'data-frontstage-surface="showcase-homepage"', "public surface data attribute");
includes(frontstageSource, 'data-testid="frontstage-showcase-workspace-shell"', "public workspace shell test id");
excludes(frontstageSource, 'frontstage-ops-main-pane', "public source ops main pane");
excludes(frontstageSource, 'data-testid="frontstage-ops-command-strip"', "public source ops command strip");
includes(deprecatedOpsSource, 'frontstage-ops-main-pane', "deprecated ops main pane class");
includes(deprecatedOpsSource, 'data-testid="frontstage-ops-command-strip"', "deprecated ops command strip test id");
includes(deprecatedOpsSource, 'data-testid="frontstage-todo-discovery"', "deprecated todo discovery anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-todo-search"', "deprecated todo search anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-todo-lane-filter"', "deprecated todo lane filter anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-todo-result-count"', "deprecated todo result count anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-role-map"', "deprecated role map anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-active-claims"', "deprecated active claims anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-open-gates"', "deprecated open gates anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-artifacts"', "deprecated artifacts anchor");
includes(deprecatedOpsSource, 'data-testid="frontstage-timeline"', "deprecated timeline anchor");
includes(frontstageSource, "long-horizon-self-iteration-rollout.public.json", "self-iteration rollout fixture import");
includes(frontstageSource, 'data-testid="frontstage-self-iteration-timeline"', "public self-iteration timeline anchor");
includes(frontstageSource, 'data-testid="frontstage-self-iteration-lane"', "public self-iteration lane anchor");
includes(frontstageSource, 'data-testid="frontstage-self-iteration-event"', "public self-iteration event anchor");
includes(frontstageSource, 'data-testid="frontstage-self-iteration-dashed-bridge"', "public self-iteration dashed bridge anchor");
includes(frontstageSource, 'data-testid="frontstage-self-iteration-truth-contract"', "public self-iteration truth contract anchor");
includes(frontstageSource, "human judgment", "human-gate plain-language copy");
includes(frontstageSource, "agent lanes", "agent-lane showcase copy");
includes(frontstageSource, "evidence writeback", "evidence writeback showcase copy");
includes(frontstageSource, 'data-testid="frontstage-showcase-motion-beam"', "human-gate animation beam");
includes(frontstageSource, 'data-testid="frontstage-state-flow-beam"', "state-flow animation beam");
excludes(frontstageSource, 'data-testid="frontstage-enable-ops-live"', "public in-page ops switch");

includes(stylesSource, ".frontstage-workspace-shell", "workspace shell CSS");
excludes(stylesSource, ".frontstage-ops-workspace", "global stylesheet deprecated ops CSS");
includes(deprecatedOpsStyles, ".frontstage-ops-workspace", "deprecated ops workspace CSS");
includes(deprecatedOpsStyles, ".frontstage-ops-main-pane", "deprecated ops main pane CSS");
includes(deprecatedOpsStyles, ".frontstage-ops-command-strip", "deprecated ops command strip CSS");
includes(stylesSource, ".frontstage-showcase-workspace", "showcase workspace CSS");
includes(stylesSource, "@media (max-width: 640px)", "responsive command strip CSS");
includes(stylesSource, "@media (prefers-reduced-motion: reduce)", "reduced motion fallback");

includes(browserSmoke, "desktop-frontstage-live", "ops visual screenshot smoke");
includes(browserSmoke, "mobile-frontstage", "mobile visual screenshot smoke");
includes(browserSmoke, "assertNoHorizontalOverflow", "overflow visual acceptance");
includes(browserSmoke, "frontstage-showcase-motion-beam", "showcase motion visual check");
includes(browserSmoke, "frontstage-self-iteration-lane", "self-iteration lane browser check");
includes(browserSmoke, "frontstage-self-iteration-dashed-bridge", "self-iteration bridge browser check");
includes(browserSmoke, "frontstage-todo-search", "ops search interaction check");
includes(browserSmoke, "frontstage-todo-lane-filter", "ops filter interaction check");
includes(browserSmoke, "Ops statusUrl must be relative or loopback", "loopback-source guard smoke");

includes(packageSource, '"smoke:frontstage-design-baseline"', "package script");

console.log("dashboard-frontstage-design-baseline smoke ok");
