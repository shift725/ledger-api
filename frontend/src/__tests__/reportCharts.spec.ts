import { describe, it, expect } from 'vitest'
import { resolveCssVar } from '@/lib/reportCharts'

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
