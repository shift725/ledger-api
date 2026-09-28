import { describe, it, expect } from 'vitest'
import { formatAmount, txnDisplayName } from '@/lib/format'

describe('formatAmount（契約 decimal 字串 → 顯示字串）', () => {
  it('整數部分加千分位', () => {
    expect(formatAmount('52000.00')).toBe('52,000')
    expect(formatAmount('1234567.89')).toBe('1,234,567.89')
  })

  it('負號保留', () => {
    expect(formatAmount('-15000.00')).toBe('-15,000')
  })

  it('全零小數部省略；真實小數原樣', () => {
    expect(formatAmount('0.00')).toBe('0')
    expect(formatAmount('45.50')).toBe('45.50')
  })

  it('無幣別符號、短數不變形', () => {
    expect(formatAmount('123')).toBe('123')
    expect(formatAmount('999.5')).toBe('999.5')
  })
})

describe('txnDisplayName（交易顯示名稱：名字 → 標籤 → 分類 → 未命名）', () => {
  it.each([
    {
      case: '有名字就用名字，標籤與分類都不看',
      txn: { name: '午餐', tag_names: ['早餐'], category_name: '餐飲' },
      expected: '午餐',
    },
    {
      case: '沒名字、一個標籤 → 該標籤',
      txn: { name: '', tag_names: ['早餐'], category_name: null },
      expected: '早餐',
    },
    {
      // 給定順序刻意與碼位序相反（外 U+5916 < 早 U+65E9）：證明照 API 給的順序串、不自行排序
      case: '沒名字、多個標籤 → 以「, 」串接，照給定順序',
      txn: { name: '', tag_names: ['早餐', '外食'], category_name: null },
      expected: '早餐, 外食',
    },
    {
      case: '沒名字、有標籤也有分類 → 標籤優先',
      txn: { name: '', tag_names: ['早餐'], category_name: '餐飲' },
      expected: '早餐',
    },
    {
      case: '沒名字、沒標籤 → 分類',
      txn: { name: '', tag_names: [], category_name: '餐飲' },
      expected: '餐飲',
    },
    {
      case: '名字、標籤、分類都沒有 → 未命名',
      txn: { name: '', tag_names: [], category_name: null },
      expected: '未命名',
    },
  ])('$case', ({ txn, expected }) => {
    expect(txnDisplayName(txn)).toBe(expected)
  })
})
