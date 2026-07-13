import { describe, it, expect } from 'vitest'
import {
  resolveCssVar,
  toBalanceHistoryChart,
  toCategoryDoughnut,
  toTagBar,
  balanceRows,
  categoryRows,
  tagRows,
} from '@/lib/reportCharts'

describe('resolveCssVar', () => {
  it('解析 :root 上定義的 CSS 變數為實際值', () => {
    document.documentElement.style.setProperty('--dot-probe', '#DA7A1C')
    expect(resolveCssVar('var(--dot-probe)')).toBe('#DA7A1C')
  })

  it('變數未定義時降級為原字串（無樣式的測試環境走此路）', () => {
    expect(resolveCssVar('var(--never-defined)')).toBe('var(--never-defined)')
  })

  it('非 var() 值原樣通過（如溢出色的 hsl）', () => {
    expect(resolveCssVar('hsl(137 65% 45%)')).toBe('hsl(137 65% 45%)')
    expect(resolveCssVar('#123456')).toBe('#123456')
  })
})

describe('toBalanceHistoryChart', () => {
  it('多帳戶不同起月 → 聯集月份軸，落後帳戶前導 null；字串轉 number', () => {
    const data = toBalanceHistoryChart([
      {
        account_id: 'a',
        account_name: 'A',
        months: [
          { month: '2026-03', balance: '100.00' },
          { month: '2026-04', balance: '150.00' },
          { month: '2026-05', balance: '150.00' },
        ],
      },
      {
        account_id: 'b',
        account_name: 'B',
        months: [{ month: '2026-05', balance: '900.00' }],
      },
    ])
    expect(data.labels).toEqual(['2026-03', '2026-04', '2026-05'])
    expect(data.datasets[0]!.data).toEqual([100, 150, 150]) // A：字串→number
    expect(data.datasets[1]!.data).toEqual([null, null, 900]) // B：首月前填 null
    expect(data.datasets[0]!.label).toBe('A')
  })

  it('空輸入 → 無 labels 無 dataset（供空態判斷）', () => {
    const data = toBalanceHistoryChart([])
    expect(data.labels).toEqual([])
    expect(data.datasets).toEqual([])
  })
})

describe('toCategoryDoughnut', () => {
  const breakdown = {
    year: 2026,
    month: 7,
    categories: [
      { category_id: 'c1', category_name: '餐飲', income: '0.00', expense: '800.00' },
      { category_id: 'c2', category_name: '薪水', income: '5000.00', expense: '0.00' },
      { category_id: null, category_name: null, income: '0.00', expense: '50.00' },
    ],
  }

  it('支出別：篩掉 expense=0，未分類命名「未分類」且著中性灰', () => {
    const d = toCategoryDoughnut(breakdown, 'expense')
    expect(d.labels).toEqual(['餐飲', '未分類']) // 薪水 expense 0 → 不進
    expect(d.datasets[0]!.data).toEqual([800, 50])
    const bg = d.datasets[0]!.backgroundColor as string[]
    expect(bg[0]).toBe('var(--dot-1)') // 首個分類 → 色盤第一色
    expect(bg[1]).toBe('var(--color-ink-2)') // 未分類 → 中性灰、不佔色盤
  })

  it('收入別：只留 income>0（同一份資料、切 flow 換值）', () => {
    const d = toCategoryDoughnut(breakdown, 'income')
    expect(d.labels).toEqual(['薪水'])
    expect(d.datasets[0]!.data).toEqual([5000])
  })
})

describe('toTagBar', () => {
  const breakdown = {
    year: 2026,
    month: 7,
    tags: [
      { tag_id: 't1', tag_name: '固定', income: '0.00', expense: '2000.00' },
      { tag_id: 't2', tag_name: '訂閱', income: '0.00', expense: '400.00' },
    ],
  }

  it('支出別：橫條標籤與值，dataset label＝支出', () => {
    const b = toTagBar(breakdown, 'expense')
    expect(b.labels).toEqual(['固定', '訂閱'])
    expect(b.datasets[0]!.data).toEqual([2000, 400])
    expect(b.datasets[0]!.label).toBe('支出')
  })

  it('收入別全 0 → 空（供空態判斷）', () => {
    expect(toTagBar(breakdown, 'income').labels).toEqual([])
  })
})

describe('文字表 row 函數（精確金額用契約字串）', () => {
  it('balanceRows：取月序列末項為目前餘額；無月份 → 0.00', () => {
    const rows = balanceRows([
      {
        account_id: 'a',
        account_name: '現金',
        months: [
          { month: '2026-05', balance: '100.00' },
          { month: '2026-07', balance: '250.00' },
        ],
      },
      { account_id: 'b', account_name: '台新', months: [] },
    ])
    expect(rows[0]).toMatchObject({ label: '現金', balance: '250.00' })
    expect(rows[1]).toMatchObject({ label: '台新', balance: '0.00' })
  })

  it('categoryRows：篩 flow>0、未分類命名+灰，金額保留契約字串（非 Number）', () => {
    const rows = categoryRows(
      {
        year: 2026,
        month: 7,
        categories: [
          { category_id: 'c1', category_name: '餐飲', income: '0.00', expense: '800.50' },
          { category_id: 'c2', category_name: '薪水', income: '5000.00', expense: '0.00' },
          { category_id: null, category_name: null, income: '0.00', expense: '50.00' },
        ],
      },
      'expense',
    )
    expect(rows.map((r) => r.label)).toEqual(['餐飲', '未分類'])
    expect(rows[0]!.amount).toBe('800.50') // 精確字串保留，不轉 Number
    expect(rows[1]!.color).toBe('var(--color-ink-2)')
  })

  it('tagRows：篩 flow>0，金額保留契約字串', () => {
    const rows = tagRows(
      {
        year: 2026,
        month: 7,
        tags: [{ tag_id: 't1', tag_name: '固定', income: '0.00', expense: '2000.00' }],
      },
      'expense',
    )
    expect(rows).toHaveLength(1)
    expect(rows[0]!.amount).toBe('2000.00')
  })
})
