import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(resolve(__dirname, 'package.json'), 'utf-8'))

const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'
const wsTarget  = apiTarget.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [
    tailwindcss(),
    vue(),
  ],
  define: {
    // Single source of truth for the app version — read from package.json
    // at build time and injected into every bundle. Used by the Settings
    // About card and the sidebar footer so they always reflect what is
    // actually shipped.
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
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
