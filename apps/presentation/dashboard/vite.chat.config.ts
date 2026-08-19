import { readFileSync } from "node:fs";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

const dashboardPublicDir = resolve(import.meta.dirname, "public");
const sharedPwaAssets = ["manifest.webmanifest", "pwa/icon-192.png", "pwa/icon-512.png"] as const;

function emitSharedPwaAssets(): Plugin {
  return {
    name: "loopx-shared-dashboard-pwa-assets",
    generateBundle() {
      for (const relativePath of sharedPwaAssets) {
        this.emitFile({
          type: "asset",
          fileName: relativePath,
          source: readFileSync(resolve(dashboardPublicDir, relativePath)),
        });
      }
    },
  };
}

export default defineConfig({
  root: resolve(import.meta.dirname, "chat"),
  base: "/chat/",
  // The chat bundle shares the root dashboard's manifest and icons without
  // copying unrelated showcase assets into the packaged chat directory.
  publicDir: false,
  plugins: [react(), tailwindcss(), emitSharedPwaAssets()],
  build: {
    outDir: resolve(import.meta.dirname, "../../../loopx/web/chat"),
    emptyOutDir: true,
  },
});
