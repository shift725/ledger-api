import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
    tailwindcss(),
    // PWA：build 時由 Workbox 生成 service worker，precache app shell（離線可開殼）。
    // 註冊碼自動注入（injectRegister 預設 auto），app 碼不 import virtual module，
    // 測試環境因此零 stub。dev 模式不啟 SW（devOptions 預設關）——避免開發時吃到快取。
    VitePWA({
      // 新版部署後 SW 自動接管，使用者不會卡在舊殼。
      registerType: 'autoUpdate',
      includeAssets: ['apple-touch-icon.png'],
      manifest: {
        name: '晴空記帳',
        short_name: '晴空',
        description: '個人記帳簿——帳戶、交易、報表與定期定額',
        lang: 'zh-Hant',
        theme_color: '#1478a8', // --color-brand-fill
        background_color: '#f5f1e8', // --color-bg
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icons/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // SPA 導航離線時 fallback 到 index.html，但這些路徑由伺服器（Django）處理、
        // 絕不能被 SW 攔去回 SPA 殼：/api（JSON API）、/admin（Django admin，同源反代）、
        // /static（admin/DRF 靜態檔）。少了 admin/static，瀏覽器導航到 /admin 會被 SW
        // 餵 index.html → 只剩空殼（nginx 已把它們反代給 web，兩處排除須一致）。
        navigateFallbackDenylist: [/^\/api/, /^\/admin/, /^\/static/],
      },
    }),
  ],
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
  // preview 不繼承 server.proxy，要自己設一份：service worker 只存在於 build 產物，
  // PWA 煙測（安裝、離線、佇列補送）得在 preview 站打真後端。
  preview: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
