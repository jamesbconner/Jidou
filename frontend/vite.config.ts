import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
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
        headers: { 'X-API-Key': process.env.JIDOU_API_KEY ?? '' },
      },
      '/docs': {
        target: 'http://localhost:8192',
        changeOrigin: true,
        headers: { 'X-API-Key': process.env.JIDOU_API_KEY ?? '' },
      },
      '/openapi.json': {
        target: 'http://localhost:8192',
        changeOrigin: true,
        headers: { 'X-API-Key': process.env.JIDOU_API_KEY ?? '' },
      },
      '/ws': {
        target: 'ws://localhost:8192',
        ws: true,
        changeOrigin: true,
        headers: { 'X-API-Key': process.env.JIDOU_API_KEY ?? '' },
      },
    },
  },
})
