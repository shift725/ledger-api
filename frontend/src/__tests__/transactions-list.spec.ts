import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { http, HttpResponse } from 'msw'
import TransactionsView from '@/views/TransactionsView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

// 手動觸發 IntersectionObserver 的 stub：捕捉 callback，測試自己「捲到底」。
let ioTrigger: (() => void) | null = null
class IOStub {
  constructor(cb: IntersectionObserverCallback) {
    ioTrigger = () =>
      cb(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      )
  }
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

async function mountList(isDesktop: boolean): Promise<{ wrapper: VueWrapper; router: Router }> {
  stubViewport(isDesktop)
  vi.stubGlobal('IntersectionObserver', IOStub)
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/transactions')
  const wrapper = mount(TransactionsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

// 兩頁罐頭：page1 → rowA + next；page2 → rowB + next=null。
function twoPageHandler(counter?: { n: number }) {
  return http.get('*/api/ledger/transactions/', ({ request }) => {
    if (counter) counter.n++
    const page = new URL(request.url).searchParams.get('page') ?? '1'
    const row = (id: string, name: string) => ({
      id,
      account: 'acc-1',
      account_name: '現金',
      category: null,
      category_name: null,
      amount: '100.00',
      type: 'expense',
      name,
      description: '',
      occurred_at: '2026-07-10T12:00:00+08:00',
      tags: [],
      tag_names: [],
      source_rule: null,
    })
    return page === '2'
      ? HttpResponse.json({
          count: 25,
          next: null,
          previous: '/x?page=1',
          results: [row('t-b', 'rowB')],
        })
      : HttpResponse.json({
          count: 25,
          next: '/x?page=2',
          previous: null,
          results: [row('t-a', 'rowA')],
        })
  })
}

beforeEach(() => {
  localStorage.clear()
})
afterEach(() => {
  ioTrigger = null
  vi.unstubAllGlobals()
})

describe('TransactionsView — 列項顯示', () => {
  it('name fallback、自動徽章、金額；進頁恰 1 發列表請求', async () => {
    const counter = { n: 0 }
    server.use(
      http.get('*/api/ledger/transactions/', () => {
        counter.n++
        return HttpResponse.json({
          count: 4,
          next: null,
          previous: null,
          results: [
            {
              id: 't1',
              account: 'acc-1',
              account_name: '現金',
              category: 'cat-food',
              category_name: '餐飲',
              amount: '120.00',
              type: 'expense',
              name: '午餐',
              description: '',
              occurred_at: '2026-07-12T12:00:00+08:00',
              tags: [],
              tag_names: [],
              source_rule: null,
            },
            {
              id: 't2',
              account: 'acc-2',
              account_name: '台新銀行',
              category: 'cat-salary',
              category_name: '薪水',
              amount: '52000.00',
              type: 'income',
              name: '',
              description: '',
              occurred_at: '2026-07-01T09:00:00+08:00',
              tags: [],
              tag_names: [],
              source_rule: null,
            },
            {
              id: 't3',
              account: 'acc-2',
              account_name: '台新銀行',
              category: 'cat-home',
              category_name: '居住',
              amount: '15000.00',
              type: 'expense',
              name: '',
              description: '',
              occurred_at: '2026-07-05T00:00:00+08:00',
              tags: [],
              tag_names: [],
              source_rule: 'rule-1',
            },
            {
              id: 't4',
              account: 'acc-1',
              account_name: '現金',
              category: null,
              category_name: null,
              amount: '60.00',
              type: 'expense',
              name: '',
              description: '',
              occurred_at: '2026-06-30T08:00:00+08:00',
              tags: [],
              tag_names: [],
              source_rule: null,
            },
          ],
        })
      }),
    )
    const { wrapper } = await mountList(true)

    expect(wrapper.text()).toContain('午餐')
    expect(wrapper.text()).toContain('薪水') // name 空 → category_name
    expect(wrapper.text()).toContain('未命名') // name 與 category_name 皆空
    expect(wrapper.text()).toContain('自動') // source_rule 非 null → 徽章
    expect(wrapper.text()).toContain('52,000')
    expect(counter.n).toBe(1) // 進頁恰一發
  })

  it('is_transfer 交易顯示「轉帳」徽章', async () => {
    server.use(
      http.get('*/api/ledger/transactions/', () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 'tx',
              account: 'acc-1',
              account_name: '現金',
              category: null,
              category_name: null,
              amount: '1000.00',
              type: 'expense',
              name: '轉去銀行',
              description: '',
              occurred_at: '2026-07-20T10:00:00+08:00',
              tags: [],
              tag_names: [],
              source_rule: null,
              is_transfer: true,
            },
          ],
        }),
      ),
    )
    const { wrapper } = await mountList(true)
    expect(wrapper.text()).toContain('轉帳')
  })

  it('查無資料 → 空態文案', async () => {
    server.use(
      http.get('*/api/ledger/transactions/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    )
    const { wrapper } = await mountList(true)
    expect(wrapper.text()).toContain('沒有交易')
  })
})

describe('TransactionsView — 雙分頁', () => {
  it('桌面：頁碼列出、點頁替換結果（非附加）', async () => {
    server.use(twoPageHandler())
    const { wrapper } = await mountList(true)
    expect(wrapper.text()).toContain('rowA')

    const pageBtn = wrapper.findAll('button').find((b) => b.text() === '2')
    expect(pageBtn).toBeTruthy()
    await pageBtn!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('rowB')
    expect(wrapper.text()).not.toContain('rowA') // 替換，非附加
  })

  it('手機：捲到 sentinel 且 next 非 null → 附加下一頁', async () => {
    server.use(twoPageHandler())
    const { wrapper } = await mountList(false)
    expect(wrapper.text()).toContain('rowA')
    expect(ioTrigger).toBeTruthy()

    ioTrigger!()
    await flushPromises()

    expect(wrapper.text()).toContain('rowA') // 附加：舊列仍在
    expect(wrapper.text()).toContain('rowB')
  })

  it('手機：next=null 時捲到底不再抓', async () => {
    const counter = { n: 0 }
    server.use(
      http.get('*/api/ledger/transactions/', () => {
        counter.n++
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 't1',
              account: 'acc-1',
              account_name: '現金',
              category: null,
              category_name: null,
              amount: '10.00',
              type: 'expense',
              name: 'only',
              description: '',
              occurred_at: '2026-07-10T12:00:00+08:00',
              tags: [],
              tag_names: [],
              source_rule: null,
            },
          ],
        })
      }),
    )
    const { wrapper } = await mountList(false)
    expect(wrapper.text()).toContain('only')
    ioTrigger!()
    await flushPromises()
    expect(counter.n).toBe(1) // next 為 null → 不觸發第二發
  })
})
