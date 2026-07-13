// 報表圖表的資料轉換與顏色解析。純函數，不碰 Chart.js runtime（型別除外）——
// 圖表實例的生命週期在 ChartCanvas.vue，這裡只產 dataset 與解析顏色，便於單測。

// Chart.js 畫在 canvas 2d context 上，無法解析 CSS 的 `var(--x)`；色點色盤是
// `var(--dot-N)` 字串，進 dataset 前必須解成實色。瀏覽器用 getComputedStyle 從
// :root 讀值；測試環境無樣式表 → 讀到空字串 → 原樣回傳（單測驗變數名有流動，
// 實色靠瀏覽器手測）。非 var() 值（如溢出色 hsl）原樣通過。
export function resolveCssVar(value: string): string {
  const trimmed = value.trim()
  if (!/^var\(--[\w-]+\)$/.test(trimmed)) return value
  const name = trimmed.slice(4, -1) // 去掉 `var(` 與 `)`，留 `--name`
  const resolved = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return resolved || value
}
