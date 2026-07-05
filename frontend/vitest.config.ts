import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/tests/setup.ts'],
    // Node >=22.1.x has an unresolved worker-thread/VM crash
    // (https://github.com/nodejs/node/issues/54735) that can kill vitest's
    // worker process partway through a local run on some machines. These
    // settings reduce how often it's hit locally; CI runs on Linux, where
    // it does not reproduce, so CI is the reliable signal.
    pool: 'forks',
    isolate: false,
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
})
