/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' so the same build works under /next/ and /; hash routing means no server rewrites.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: '../run-engine/ui_dist', emptyOutDir: true, sourcemap: false,
    // mermaid's lazy elk chunk is ~1.46 MB; PrdTab.tsx only fetches it when a PRD has a diagram.
    chunkSizeWarningLimit: 1500,
    manifest: true,
    // The share page's CSP has no data: source, so fonts stay files.
    assetsInlineLimit: 0,
    rolldownOptions: { input: { main: 'index.html', share: 'share.html' }, output: { codeSplitting: { groups: [
      { name: 'vendor', test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler|@radix-ui|@tanstack|cmdk)[\\/]/ },
    ] } } },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8420' } },
  test: { environment: 'jsdom', globals: false, setupFiles: ['./src/test-setup.ts'] },
});
