import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Served from https://masnun-siam.github.io/ai-workflow/
export default defineConfig({ base: '/ai-workflow/', plugins: [react()] });
