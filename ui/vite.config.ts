/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' so the same build works under /next/ and /; hash routing means no server rewrites.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { outDir: '../run-engine/ui_dist', emptyOutDir: true, sourcemap: false },
  server: { proxy: { '/api': 'http://127.0.0.1:8420' } },
  test: { environment: 'jsdom', globals: false, setupFiles: ['./src/test-setup.ts'] },
});
