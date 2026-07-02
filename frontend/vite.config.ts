import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  // loadEnv reads .env, .env.local, .env.{mode}, etc. — empty prefix loads all
  // vars (not just VITE_*) so JIDOU_API_KEY is available without shell export.
  const env = loadEnv(mode, process.cwd(), '')
  const apiKey = env.JIDOU_API_KEY ?? ''

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    build: {
      outDir: 'dist',
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8192',
          changeOrigin: true,
          headers: { 'X-API-Key': apiKey },
        },
        '/docs': {
          target: 'http://localhost:8192',
          changeOrigin: true,
          headers: { 'X-API-Key': apiKey },
        },
        '/openapi.json': {
          target: 'http://localhost:8192',
          changeOrigin: true,
          headers: { 'X-API-Key': apiKey },
        },
        '/ws': {
          target: 'ws://localhost:8192',
          ws: true,
          changeOrigin: true,
          headers: { 'X-API-Key': apiKey },
        },
      },
    },
  }
})
