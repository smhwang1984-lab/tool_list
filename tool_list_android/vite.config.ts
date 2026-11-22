import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: { outDir: 'dist', target: 'es2022', sourcemap: true, chunkSizeWarningLimit: 1000 },
  worker: { format: 'es' },
  server: { fs: { allow: ['..'] } },
  test: { include: ['tests/**/*.test.ts'], environment: 'node' },
} as never);
