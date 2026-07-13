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

// 走勢圖選項：y 軸刻度與 tooltip 皆走 formatAmount（tooltip 取繪圖 float，精度邊界同上）。
export function lineChartOptions(): ChartOptions<'line'> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'bottom' },
      tooltip: {
        callbacks: {
          label: (ctx) => `${ctx.dataset.label}: ${formatAmount(String(ctx.parsed.y))}`,
        },
      },
    },
    scales: {
      y: { ticks: { callback: (v) => formatAmount(String(v)) } },
    },
  }
}

// 分類環圈：單值 FK，各桶加總＝當月總額，環圈語意成立。依選定收支別（flow）取值；
// 該別為 0 的分類不進圈（免無形切片汙染圖例）。未分類（category_id=null）著中性灰、
// 不佔色盤名額。by-category 一發回收支雙值 → 切 flow 純換值、不重抓。
export function toCategoryDoughnut(
  breakdown: CategoryBreakdown,
  flow: Flow,
): ChartData<'doughnut'> {
  const items = breakdown.categories.filter((c) => Number(c[flow]) > 0)
  const assign = createDotAssigner()
  return {
    labels: items.map((c) => c.category_name ?? '未分類'),
    datasets: [
      {
        data: items.map((c) => Number(c[flow])),
        backgroundColor: items.map((c) =>
          c.category_id === null
            ? resolveCssVar('var(--color-ink-2)')
            : resolveCssVar(assign(c.category_id)),
        ),
      },
    ],
  }
}

// 標籤橫條：M2M 可重疊維度，各標籤金額加總可破當月總額 → 禁圓餅（合計 100% 不成立），
// 用橫向長條（indexAxis:'y'）。其餘同分類：flow 取值、0 值不進、切 flow 不重抓。
export function toTagBar(breakdown: TagBreakdown, flow: Flow): ChartData<'bar'> {
  const items = breakdown.tags.filter((t) => Number(t[flow]) > 0)
  const assign = createDotAssigner()
  return {
    labels: items.map((t) => t.tag_name),
    datasets: [
      {
        label: flow === 'expense' ? '支出' : '收入',
        data: items.map((t) => Number(t[flow])),
        backgroundColor: items.map((t) => resolveCssVar(assign(t.tag_id))),
      },
    ],
  }
}

export function doughnutChartOptions(): ChartOptions<'doughnut'> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom' },
      tooltip: {
        callbacks: { label: (ctx) => `${ctx.label}: ${formatAmount(String(ctx.parsed))}` },
      },
    },
  }
}

export function barChartOptions(): ChartOptions<'bar'> {
  return {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (ctx) => formatAmount(String(ctx.parsed.x)) } },
    },
    scales: {
      x: { ticks: { callback: (v) => formatAmount(String(v)) } },
    },
  }
}
