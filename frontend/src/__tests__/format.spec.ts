import { describe, it, expect } from 'vitest'
import { formatAmount } from '@/lib/format'

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
