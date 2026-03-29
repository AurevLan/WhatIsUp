import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'
const wsTarget  = apiTarget.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [
    tailwindcss(),
    vue(),
  ],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.js'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/ws':  { target: wsTarget,  ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
})
