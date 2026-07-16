// Lighthouse CI：accessibility 守門（本機與 CI 同一指令 `npx lhci autorun` 可重現）。
// 只掃 login/register 公開頁——preview 無 API proxy、未登入的受保護路由都會被守衛
// 導回 /login，掃了也是同一頁；深頁的 a11y 靠對比 AA 鐵則人工把關。
// PWA installability 不在此守（Lighthouse 12 已移除 PWA category），
// 由 CI 的 build 產物斷言＋實機安裝驗證承接。
module.exports = {
  ci: {
    collect: {
      startServerCommand: 'npm run preview -- --port 4173 --strictPort',
      startServerReadyPattern: 'Local',
      url: ['http://localhost:4173/login', 'http://localhost:4173/register'],
      numberOfRuns: 1, // a11y 審計是確定性的，不需多輪取中位數（那是 perf 的事）
      settings: {
        onlyCategories: ['accessibility'],
      },
    },
    assert: {
      assertions: {
        // 實跑兩頁皆滿分、lhci 版本由 lockfile 釘死（分數只受自家代碼影響）→ 直接鎖滿分
        'categories:accessibility': ['error', { minScore: 1 }],
      },
    },
  },
}
