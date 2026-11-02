import { defineConfig } from 'vite';

export default defineConfig({
  cacheDir: '../runtime/datasource-vite-cache',
  build: { outDir: '../runtime/datasource-dist', emptyOutDir: true },
  server: { host: '127.0.0.1', strictPort: true },
});
