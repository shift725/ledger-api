import { describe, it, expect } from 'vitest'
import { DOT_PALETTE, createDotAssigner } from '@/lib/dots'

describe('createDotAssigner（範圍內出現序指派）', () => {
  it('確定性：同序列輸入，兩個 assigner 產出相同結果', () => {
    const ids = ['c3', 'a1', 'b2', 'a1', 'd4']
    const first = createDotAssigner()
    const second = createDotAssigner()
    expect(ids.map((id) => first(id))).toEqual(ids.map((id) => second(id)))
  })

  it('前 10 個 id 依出現序發滿色盤且零撞色', () => {
    const assign = createDotAssigner()
    const colors = Array.from({ length: 10 }, (_, i) => assign(`id-${i}`))
    expect(colors).toEqual(DOT_PALETTE)
    expect(new Set(colors).size).toBe(10)
  })

  it('同 id 再現拿同色，不佔新色', () => {
    const assign = createDotAssigner()
    const first = assign('x')
    assign('y')
    expect(assign('x')).toBe(first)
    expect(assign('z')).toBe(DOT_PALETTE[2])
  })

  it('第 11 個起溢出色互異且不與色盤重複', () => {
    const assign = createDotAssigner()
    const colors = Array.from({ length: 15 }, (_, i) => assign(`id-${i}`))
    expect(new Set(colors).size).toBe(15)
    for (const color of colors.slice(10)) {
      expect(DOT_PALETTE).not.toContain(color)
    }
  })
})
