import { defineConfig } from "vitest/config";
import preact from "@preact/preset-vite";

// The build is committed at ../internal/web/dist and embedded by the Go binary.
export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "../internal/web/dist",
    emptyOutDir: true,
    target: "es2022",
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8420" },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
