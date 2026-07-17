import { defineConfig, devices } from '@playwright/test'

// E2E 煙測設定：打「已經起好的」容器全棧（nginx 服 SPA＋同源反代 /api）。
// 刻意不用 webServer 自動起站——棧的生命週期歸 docker compose／CI 管，
// 這裡只負責「對某個 URL 跑流程」；換掉 E2E_BASE_URL 就能打任何一站
// （本機容器、CI、部署後的正式站），同一份煙測多處複用。
export default defineConfig({
  testDir: './e2e',
  // 煙測要誠實：不 retry——flaky 就看 trace 修根因，不用重跑蓋掉。
  retries: 0,
  // CI 上禁止 test.only 混入：只剩一條被跑，整套會假綠。
  forbidOnly: !!process.env.CI,
  use: {
    // 寫 127.0.0.1 不寫 localhost：Windows／容器環境 localhost 可能先解析成
    // IPv6 的 ::1，而服務只聽 IPv4，會得到莫名的連線失敗。
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1',
    // 每跑必錄：trace 記下每一步的 DOM 快照、網路與 console，事後可逐步回放；
    // 綠的也留證——煙測的產出一半是「通過」，一半是「通過的證據」。
    trace: 'on',
  },
  // 煙測單瀏覽器就夠：目標是「接起來是通的」，不是跨瀏覽器相容性矩陣。
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
