import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.MELLOWDAY_DEV_API_URL || "http://127.0.0.1:8000",
      },
    },
  },
  build: { sourcemap: false },
});
