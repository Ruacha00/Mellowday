import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/static/replacement/",
  plugins: [react()],
  build: {
    outDir: fileURLToPath(
      new URL("../src/mellowday/web_app/static/replacement", import.meta.url),
    ),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/chunks/[name]-[hash].js",
        assetFileNames: (assetInfo) => {
          const sourceName = assetInfo.names[0] ?? "asset";
          if (sourceName.endsWith(".woff2")) {
            return "assets/fonts/[name]-[hash][extname]";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
