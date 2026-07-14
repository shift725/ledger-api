import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { http, HttpResponse } from 'msw'
import TransactionsView from '@/views/TransactionsView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

// 記錄每一發交易列表請求的 query，用來斷言「URL → API 參數」與請求數。
const listQueries: URLSearchParams[] = []

class IOStub {
  constructor() {}
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

function stubViewport(isDesktop: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: isDesktop,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }))
}

async function mountAt(path: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  stubViewport(true)
  vi.stubGlobal('IntersectionObserver', IOStub)
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(path)
  const wrapper = mount(TransactionsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  localStorage.clear()
  listQueries.length = 0
  server.use(
    http.get('*/api/ledger/transactions/', ({ request }) => {
      listQueries.push(new URL(request.url).searchParams)
      return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('TransactionsView — 過濾與 URL 同步', () => {
  it('進頁帶 query → 首發請求帶對應參數；生效條件成 chips', async () => {
    const { wrapper } = await mountAt('/transactions?type=expense&search=coffee')

    expect(listQueries).toHaveLength(1)
    expect(listQueries[0]!.get('type')).toBe('expense')
    expect(listQueries[0]!.get('search')).toBe('coffee')

    expect(wrapper.text()).toContain('支出') // type chip
    expect(wrapper.text()).toContain('coffee') // search chip
  })

  it('改過濾（type select）→ router.replace 更新 query＋恰 1 發新請求', async () => {
    const { wrapper, router } = await mountAt('/transactions')
    expect(listQueries).toHaveLength(1) // 進頁一發

    const typeSelect = wrapper.find('select[data-test="filter-type"]')
    await typeSelect.setValue('income')
    await flushPromises()

    expect(router.currentRoute.value.query.type).toBe('income')
    expect(listQueries).toHaveLength(2) // 改一次＝再一發
    expect(listQueries[1]!.get('type')).toBe('income')
    expect(listQueries[1]!.get('page')).toBeNull() // 過濾改動回第一頁（無 page 參數）
  })

  it('移除 chip → 該參數自 URL 與請求消失、重抓', async () => {
    const { wrapper, router } = await mountAt('/transactions?type=expense')
    expect(wrapper.text()).toContain('支出')

    const chipClose = wrapper.find('[data-test="chip-remove"]')
    expect(chipClose.exists()).toBe(true)
    await chipClose.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.type).toBeUndefined()
    expect(listQueries.at(-1)!.get('type')).toBeNull()
    // 「支出」也是面板的 <option> 文字，故斷言 chip 本身消失（type 是唯一過濾）
    expect(wrapper.find('[data-test="chip-remove"]').exists()).toBe(false)
  })

  it('搜尋輸入（change）→ URL 帶 search、請求帶 search', async () => {
    const { wrapper, router } = await mountAt('/transactions')
    const searchInput = wrapper.find('input[data-test="filter-search"]')
    await searchInput.setValue('拿鐵')
    await searchInput.trigger('change')
    await flushPromises()

    expect(router.currentRoute.value.query.search).toBe('拿鐵')
    expect(listQueries.at(-1)!.get('search')).toBe('拿鐵')
  })

  it('多標籤過濾以 CSV 單值送出（非重複參數）', async () => {
    // 後端 UUIDInFilter 拆逗號、重複參數只認最後一個 → 必須 CSV。
    await mountAt('/transactions?tags_any=a,b')
    const last = listQueries.at(-1)!
    expect(last.get('tags_any')).toBe('a,b') // 逗號合併，非 'a'（重複參數的首值）
    expect(last.getAll('tags_any')).toEqual(['a,b']) // 只有一個 tags_any 參數
  })

  it('account 過濾用 reference 名稱成 chip', async () => {
    const { wrapper } = await mountAt('/transactions?account=acc-2')
    await flushPromises() // 等 reference.ensure() 落地
    expect(wrapper.text()).toContain('台新銀行') // acc-2 的 name
  })
})

// 標籤＝filter chips：按鈕本身表達選取態（aria-pressed），不進下方生效條件 chips。
describe('TransactionsView — 標籤 filter chips', () => {
  async function tagChip(wrapper: VueWrapper, name: string) {
    await flushPromises() // 等 reference tags 落地
    const chip = wrapper.findAll('button').find((b) => b.text().includes(name))
    expect(chip, `缺標籤 chip「${name}」`).toBeDefined()
    return chip!
  }

  it('點 chip 選取 → aria-pressed＋URL tags_any；再點取消', async () => {
    const { wrapper, router } = await mountAt('/transactions')
    const chip = await tagChip(wrapper, '固定支出')
    expect(chip.attributes('aria-pressed')).toBe('false')

    await chip.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.tags_any).toBe('tag-1')
    expect(chip.attributes('aria-pressed')).toBe('true')

    await chip.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.tags_any).toBeUndefined()
  })

  it('選取狀態只在 chip 本身，不產生生效條件 chip', async () => {
    const { wrapper } = await mountAt('/transactions?tags_any=tag-1')
    const chip = await tagChip(wrapper, '固定支出')
    expect(chip.attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-test="chip-remove"]').exists()).toBe(false)
  })

  it('mode 切換：選 1 個不顯示、選 2 個出現；切「全部」→ URL 僅 tags_all（CSV）', async () => {
    const { wrapper, router } = await mountAt('/transactions?tags_any=tag-1')
    await flushPromises()
    expect(wrapper.find('[data-test="tag-mode"]').exists()).toBe(false) // 單選時任一＝全部

    const chip2 = await tagChip(wrapper, '訂閱')
    await chip2.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.tags_any).toBe('tag-1,tag-2')
    expect(wrapper.find('[data-test="tag-mode"]').exists()).toBe(true)

    const allBtn = wrapper
      .findAll('[data-test="tag-mode"] button')
      .find((b) => b.text() === '全部')!
    await allBtn.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.tags_all).toBe('tag-1,tag-2')
    expect(router.currentRoute.value.query.tags_any).toBeUndefined()
    const last = listQueries.at(-1)!
    expect(last.get('tags_all')).toBe('tag-1,tag-2')
    expect(last.getAll('tags_all')).toEqual(['tag-1,tag-2']) // CSV 單值（重複參數後端只認最後一個）
  })

  it('tags_all 進頁 → all 模式、chip 呈選取', async () => {
    const { wrapper } = await mountAt('/transactions?tags_all=tag-1,tag-2')
    const chip = await tagChip(wrapper, '固定支出')
    expect(chip.attributes('aria-pressed')).toBe('true')
    const allBtn = wrapper
      .findAll('[data-test="tag-mode"] button')
      .find((b) => b.text() === '全部')!
    expect(allBtn.attributes('aria-pressed')).toBe('true')
    expect(listQueries.at(-1)!.get('tags_all')).toBe('tag-1,tag-2')
  })

  it('兩組並存的 URL（UI 不會產生）→ 正規化為聯集 tags_any、恰 1 發請求', async () => {
    const { router } = await mountAt('/transactions?tags_any=tag-1&tags_all=tag-2')
    await flushPromises()
    expect(router.currentRoute.value.query.tags_any).toBe('tag-1,tag-2')
    expect(router.currentRoute.value.query.tags_all).toBeUndefined()
    expect(listQueries).toHaveLength(1) // 正規化在載入前完成，不多打一發
    expect(listQueries[0]!.get('tags_any')).toBe('tag-1,tag-2')
    expect(listQueries[0]!.get('tags_all')).toBeNull()
  })
})
