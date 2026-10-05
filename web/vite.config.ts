import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// Backend dev server (uvicorn). Override with VITE_PROXY_TARGET.
const target = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8090';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api/v1': { target, changeOrigin: true },
    },
  },
});
