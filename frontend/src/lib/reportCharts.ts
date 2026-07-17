// 報表圖表的資料轉換與顏色解析。純函數，不碰 Chart.js runtime（型別除外）——
// 圖表實例的生命週期在 ChartCanvas.vue，這裡只產 dataset 與解析顏色，便於單測。

import type { ChartData, ChartOptions } from 'chart.js'
import type { components } from '@/api/schema'
import { createDotAssigner } from '@/lib/dots'
import { formatAmount } from '@/lib/format'

type BalanceHistoryAccount = components['schemas']['BalanceHistoryAccount']
type CategoryBreakdown = components['schemas']['CategoryBreakdown']
type TagBreakdown = components['schemas']['TagBreakdown']
export type Flow = 'income' | 'expense'

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

// 每帳戶月序列起點不同（各自首筆交易月）；多線共用一條時間軸＝所有帳戶月份的聯集
// （YYYY-MM 字典序即時序）。帳戶在自己首月之前的點填 null → Chart.js 斷線，語意＝
// 該帳戶當時尚不存在（spanGaps 關）。**字串→number 的唯一轉換點就在這裡**——繪圖
// 像素定位不需 decimal 精度、用 float 可接受；其餘一切文字顯示仍走 formatAmount。
export function toBalanceHistoryChart(accounts: BalanceHistoryAccount[]): ChartData<'line'> {
  const labels = [...new Set(accounts.flatMap((a) => a.months.map((m) => m.month)))].sort()
  const assign = createDotAssigner()
  const datasets = accounts.map((a) => {
    const byMonth = new Map(a.months.map((m) => [m.month, Number(m.balance)]))
    const color = resolveCssVar(assign(a.account_id))
    return {
      label: a.account_name,
      data: labels.map((l) => byMonth.get(l) ?? null),
      borderColor: color,
      backgroundColor: color,
      spanGaps: false,
      tension: 0.2,
    }
  })
  return { labels, datasets }
}

// 各帳戶目前餘額（月序列末項）＋色點，供走勢圖下方精確數字表。色點與走勢線同源
// （同一 accounts 順序、確定性 assigner）→ 顏色一致。
export interface BalanceRow {
  label: string
  balance: string
  color: string
}
export function balanceRows(accounts: BalanceHistoryAccount[]): BalanceRow[] {
  const assign = createDotAssigner()
  return accounts.map((a) => ({
    label: a.account_name,
    balance: a.months.at(-1)?.balance ?? '0.00',
    color: resolveCssVar(assign(a.account_id)),
  }))
}

// Chart.js 的軸字/圖例/格線色是寫死的預設（#666、rgba(0,0,0,.1)），不吃 CSS 變數，
// 深色下直接不可讀 → 產生選項時經 resolveCssVar 餵 token（亮色下 ink-2 ≈ 原預設，
// 視覺不變）。取值時機＝options 建立；OS 主題熱切換時已掛載圖表不重著色，離頁再進即正確。
function chartTheme() {
  return {
    text: resolveCssVar('var(--color-ink-2)'),
    grid: resolveCssVar('var(--color-hairline)'),
    surface: resolveCssVar('var(--color-card)'),
  }
}

// 走勢圖選項：y 軸刻度與 tooltip 皆走 formatAmount（tooltip 取繪圖 float，精度邊界同上）。
export function lineChartOptions(): ChartOptions<'line'> {
  const theme = chartTheme()
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'bottom', labels: { color: theme.text } },
      tooltip: {
        callbacks: {
          label: (ctx) => `${ctx.dataset.label}: ${formatAmount(String(ctx.parsed.y))}`,
        },
      },
    },
    scales: {
      x: { ticks: { color: theme.text }, grid: { color: theme.grid } },
      y: {
        ticks: { color: theme.text, callback: (v) => formatAmount(String(v)) },
        grid: { color: theme.grid },
      },
    },
  }
}

// 圖與表共用的一列：label＋契約字串金額＋已解析色。圖用 Number(amount) 定位、表用
// formatAmount(amount) 顯示精確值，顏色同一份 → 圖例與文字表天然對齊、不需各自指色。
export interface BreakdownRow {
  label: string
  amount: string
  color: string
}

// 分類：篩掉 flow 為 0 者（免無形切片）；未分類（category_id=null）著中性灰、不佔色盤名額。
export function categoryRows(breakdown: CategoryBreakdown, flow: Flow): BreakdownRow[] {
  const assign = createDotAssigner()
  return breakdown.categories
    .filter((c) => Number(c[flow]) > 0)
    .map((c) => ({
      label: c.category_name ?? '未分類',
      amount: c[flow],
      color:
        c.category_id === null
          ? resolveCssVar('var(--color-ink-2)')
          : resolveCssVar(assign(c.category_id)),
    }))
}

// 標籤：篩掉 flow 為 0 者；每標籤一色。
export function tagRows(breakdown: TagBreakdown, flow: Flow): BreakdownRow[] {
  const assign = createDotAssigner()
  return breakdown.tags
    .filter((t) => Number(t[flow]) > 0)
    .map((t) => ({ label: t.tag_name, amount: t[flow], color: resolveCssVar(assign(t.tag_id)) }))
}

// 分類環圈：單值 FK，各桶加總＝當月總額，環圈語意成立。by-category 一發回收支雙值 →
// 切 flow 純換值、不重抓。
export function toCategoryDoughnut(
  breakdown: CategoryBreakdown,
  flow: Flow,
): ChartData<'doughnut'> {
  const rows = categoryRows(breakdown, flow)
  return {
    labels: rows.map((r) => r.label),
    datasets: [
      { data: rows.map((r) => Number(r.amount)), backgroundColor: rows.map((r) => r.color) },
    ],
  }
}

// 標籤橫條：M2M 可重疊維度，各標籤加總可破當月總額 → 禁圓餅（合計 100% 不成立），
// 用橫向長條（indexAxis:'y'）。
export function toTagBar(breakdown: TagBreakdown, flow: Flow): ChartData<'bar'> {
  const rows = tagRows(breakdown, flow)
  return {
    labels: rows.map((r) => r.label),
    datasets: [
      {
        label: flow === 'expense' ? '支出' : '收入',
        data: rows.map((r) => Number(r.amount)),
        backgroundColor: rows.map((r) => r.color),
      },
    ],
  }
}

export function doughnutChartOptions(): ChartOptions<'doughnut'> {
  const theme = chartTheme()
  return {
    responsive: true,
    maintainAspectRatio: false,
    // 切片邊線預設純白，深色卡面上會出白縫 → 跟卡面同色
    elements: { arc: { borderColor: theme.surface } },
    plugins: {
      legend: { position: 'bottom', labels: { color: theme.text } },
      tooltip: {
        callbacks: { label: (ctx) => `${ctx.label}: ${formatAmount(String(ctx.parsed))}` },
      },
    },
  }
}

export function barChartOptions(): ChartOptions<'bar'> {
  const theme = chartTheme()
  return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (ctx) => formatAmount(String(ctx.parsed.x)) } },
    },
    scales: {
      x: {
        ticks: { color: theme.text, callback: (v) => formatAmount(String(v)) },
        grid: { color: theme.grid },
      },
      y: { ticks: { color: theme.text }, grid: { color: theme.grid } },
    },
  }
}
