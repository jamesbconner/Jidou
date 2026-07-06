import { defineConfig, configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/tests/setup.ts'],
    // Reduces (but does not eliminate) an intermittent worker crash on some
    // local machines. Not a full fix — see the exclude below for the actual
    // known-hanging file and tracking issue.
    pool: 'forks',
    isolate: false,
    // Hangs indefinitely with zero output before any test in the file even
    // starts — reproduces both locally (crashes the vitest worker on
    // Windows/Node 22) and in CI (hangs on Linux/Node 20 until the job
    // timeout kills it), so it is not the Node>=22.1.x VM-crash bug
    // (nodejs/node#54735) alone. Root cause not yet found — see
    // https://github.com/jamesbconner/Jidou/issues/258. Excluded so the
    // rest of the suite runs reliably in the meantime.
    exclude: [...configDefaults.exclude, 'src/tests/pages/Watchlist.test.tsx'],
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
})
