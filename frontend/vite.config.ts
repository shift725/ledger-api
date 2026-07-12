import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), vueDevTools(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // Dev-only: the app calls /api/... with relative URLs; Vite proxies them to
  // the Django container. Prod serves both under one origin via nginx, so the
  // same-origin assumption holds in both environments.
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
