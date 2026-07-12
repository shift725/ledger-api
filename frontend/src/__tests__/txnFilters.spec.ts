import { describe, it, expect } from 'vitest'
import {
  emptyFilterState,
  parseQuery,
  toQuery,
  toApiParams,
  DEFAULT_ORDERING,
} from '@/lib/txnFilters'

describe('parseQuery（route.query → 過濾狀態）', () => {
  it('空 query 得預設狀態（排序＝-occurred_at）', () => {
    expect(parseQuery({})).toEqual(emptyFilterState())
    expect(parseQuery({}).ordering).toBe(DEFAULT_ORDERING)
  })

  it('逐鍵還原；tags CSV 拆成陣列', () => {
    const s = parseQuery({
      search: '午餐',
      ordering: '-amount',
      type: 'expense',
      account: 'acc-1',
      category: 'cat-1',
      amount_min: '100',
      amount_max: '500',
      date_from: '2026-07-01',
      date_to: '2026-07-12',
      tags_any: 'a,b',
      tags_all: 'c',
    })
    expect(s).toEqual({
      search: '午餐',
      ordering: '-amount',
      type: 'expense',
      account: 'acc-1',
      category: 'cat-1',
      amountMin: '100',
      amountMax: '500',
      dateFrom: '2026-07-01',
      dateTo: '2026-07-12',
      tagsAny: ['a', 'b'],
      tagsAll: ['c'],
    })
  })

  it('非白名單 ordering／非法 type 落回預設；重複參數與 CSV 空成員都容忍', () => {
    expect(parseQuery({ ordering: 'bogus' }).ordering).toBe(DEFAULT_ORDERING)
    expect(parseQuery({ type: 'bogus' }).type).toBe('')
    expect(parseQuery({ tags_any: ['a', 'b'] }).tagsAny).toEqual(['a', 'b'])
    expect(parseQuery({ tags_any: 'a,,b' }).tagsAny).toEqual(['a', 'b'])
  })
})

describe('toQuery（狀態 → route.query，只留非預設）', () => {
  it('預設狀態 → 空 query（排序省略、無雜鍵）', () => {
    expect(toQuery(emptyFilterState())).toEqual({})
  })

  it('roundtrip：toQuery∘parseQuery 對非空狀態穩定', () => {
    const q = {
      search: '午餐',
      ordering: '-amount',
      type: 'expense',
      account: 'acc-1',
      amount_min: '100',
      date_from: '2026-07-01',
      tags_any: 'a,b',
    }
    expect(toQuery(parseQuery(q))).toEqual(q)
  })

  it('預設排序不寫入 query', () => {
    const s = emptyFilterState()
    s.ordering = DEFAULT_ORDERING
    s.search = 'x'
    expect(toQuery(s)).toEqual({ search: 'x' })
  })
})

describe('toApiParams（狀態＋page → 契約 query）', () => {
  it('空狀態、page 1 → 空 params（page 1 與預設排序皆省略）', () => {
    expect(toApiParams(emptyFilterState(), 1)).toEqual({})
  })

  it('page>1 帶 page；金額轉 number；tags 陣列直送', () => {
    const s = emptyFilterState()
    s.amountMin = '100'
    s.amountMax = '500'
    s.tagsAny = ['a', 'b']
    const p = toApiParams(s, 3)
    expect(p.page).toBe(3)
    expect(p.amount_min).toBe(100)
    expect(p.amount_max).toBe(500)
    expect(p.tags_any).toEqual(['a', 'b'])
  })

  it('日期端點：起日→當地 00:00:00、迄日→當地 23:59:59（instant 語意，tz 無關）', () => {
    const s = emptyFilterState()
    s.dateFrom = '2026-07-01'
    s.dateTo = '2026-07-12'
    const p = toApiParams(s, 1)
    // 以 instant 比對，避開機器時區差異；起點＝當地當日零點
    expect(new Date(p.occurred_after!).getTime()).toBe(new Date(2026, 6, 1, 0, 0, 0).getTime())
    // 迄點＝當地當日 23:59:59，必須嚴格早於隔日零點
    // → 隔日 00:00 的定期定額自動交易不會被 lte 誤收
    expect(new Date(p.occurred_before!).getTime()).toBe(new Date(2026, 6, 12, 23, 59, 59).getTime())
    expect(new Date(p.occurred_before!).getTime()).toBeLessThan(
      new Date(2026, 6, 13, 0, 0, 0).getTime(),
    )
  })
})
