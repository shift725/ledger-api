// 交易列表過濾：三種表示的純函數轉換，狀態邏輯全收斂在此、view 只綁定。
//   route.query  ←parseQuery / toQuery→  FilterState  ←toApiParams→  契約 query
// URL 帶「日期」(YYYY-MM-DD，好分享)；API 帶「datetime」(端點展開，見 toApiParams)。
import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import type { operations } from '@/api/schema'

type ListQuery = NonNullable<operations['ledger_transactions_list']['parameters']['query']>

// 排序白名單（契約 ordering 為自由字串，前端只暴露這四個）；預設省略。
export const ORDERINGS = ['-occurred_at', 'occurred_at', '-amount', 'amount'] as const
export type Ordering = (typeof ORDERINGS)[number]
export const DEFAULT_ORDERING: Ordering = '-occurred_at'

export interface FilterState {
  search: string
  ordering: Ordering
  type: '' | 'income' | 'expense'
  account: string
  category: string
  amountMin: string // 字串：直接綁 input，'' = 未設
  amountMax: string
  dateFrom: string // YYYY-MM-DD
  dateTo: string
  tagsAny: string[]
  tagsAll: string[]
}

export function emptyFilterState(): FilterState {
  return {
    search: '',
    ordering: DEFAULT_ORDERING,
    type: '',
    account: '',
    category: '',
    amountMin: '',
    amountMax: '',
    dateFrom: '',
    dateTo: '',
    tagsAny: [],
    tagsAll: [],
  }
}

// route.query 值為 string | (string|null)[] | null | undefined；取單值 / 拆 CSV（也吞重複參數）。
type QueryValue = LocationQuery[string] | undefined
function str(v: QueryValue): string {
  return (Array.isArray(v) ? v[0] : v) ?? ''
}
function csv(v: QueryValue): string[] {
  const raw = Array.isArray(v) ? v.filter((x) => x != null).join(',') : (v ?? '')
  return raw
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
}

export function parseQuery(q: LocationQuery): FilterState {
  const s = emptyFilterState()
  s.search = str(q.search)
  const ord = str(q.ordering)
  if ((ORDERINGS as readonly string[]).includes(ord)) s.ordering = ord as Ordering
  const t = str(q.type)
  if (t === 'income' || t === 'expense') s.type = t
  s.account = str(q.account)
  s.category = str(q.category)
  s.amountMin = str(q.amount_min)
  s.amountMax = str(q.amount_max)
  s.dateFrom = str(q.date_from)
  s.dateTo = str(q.date_to)
  s.tagsAny = csv(q.tags_any)
  s.tagsAll = csv(q.tags_all)
  return s
}

// 只寫非預設值 → URL 乾淨、可分享；tags 以 CSV 單值進 query。
export function toQuery(s: FilterState): LocationQueryRaw {
  const q: LocationQueryRaw = {}
  if (s.search) q.search = s.search
  if (s.ordering !== DEFAULT_ORDERING) q.ordering = s.ordering
  if (s.type) q.type = s.type
  if (s.account) q.account = s.account
  if (s.category) q.category = s.category
  if (s.amountMin) q.amount_min = s.amountMin
  if (s.amountMax) q.amount_max = s.amountMax
  if (s.dateFrom) q.date_from = s.dateFrom
  if (s.dateTo) q.date_to = s.dateTo
  if (s.tagsAny.length) q.tags_any = s.tagsAny.join(',')
  if (s.tagsAll.length) q.tags_all = s.tagsAll.join(',')
  return q
}

// 當地日期 → 該日「起/迄」的 UTC instant。用 .toISOString()（Z 形）而非手拼 offset：
// 兩者是同一 instant，後端 IsoDateTimeFilter 依 instant 比較，Z 形不歧義且更短。
// 迄點用 23:59:59（非隔日 00:00）→ 隔日零點的定期定額自動交易不被 lte 誤收。
function dayStartISO(date: string): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  return new Date(y, m - 1, d, 0, 0, 0).toISOString()
}
function dayEndISO(date: string): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  return new Date(y, m - 1, d, 23, 59, 59).toISOString()
}

export function toApiParams(s: FilterState, page: number): ListQuery {
  const q: ListQuery = {}
  if (s.search) q.search = s.search
  if (s.ordering !== DEFAULT_ORDERING) q.ordering = s.ordering
  if (s.type) q.type = s.type
  if (s.account) q.account = s.account
  if (s.category) q.category = s.category
  if (s.amountMin) q.amount_min = Number(s.amountMin)
  if (s.amountMax) q.amount_max = Number(s.amountMax)
  if (s.dateFrom) q.occurred_after = dayStartISO(s.dateFrom)
  if (s.dateTo) q.occurred_before = dayEndISO(s.dateTo)
  if (s.tagsAny.length) q.tags_any = s.tagsAny
  if (s.tagsAll.length) q.tags_all = s.tagsAll
  if (page > 1) q.page = page
  return q
}
