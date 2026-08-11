import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  base: process.env.LOOPX_SITE_BASE ?? "/",
  plugins: [react()],
  server: {
    fs: {
      allow: [fileURLToPath(new URL("../../..", import.meta.url))],
    },
  },
  build: {
    assetsDir: "site-assets",
    emptyOutDir: true,
  },
});
