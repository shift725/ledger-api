import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'
import { useReferenceStore } from '@/stores/reference'
import { useAuthStore } from '@/stores/auth'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

// 測試用：把 auth store 設成已登入的指定 user（持久化 key 依 user id 組）
function loginAs(id: string) {
  const auth = useAuthStore()
  auth.user = { id, username: id, email: `${id}@x.tw`, role: 'member' }
  auth.access = 'test-access'
}

describe('reference store — ensure()（SWR）', () => {
  it('冷啟：await 抓齊三份清單', async () => {
    const store = useReferenceStore()
    await store.ensure()

    expect(store.accounts.map((a) => a.id)).toEqual(['acc-1', 'acc-2'])
    expect(store.categories.map((c) => c.id)).toEqual(['cat-food', 'cat-home', 'cat-salary'])
    expect(store.tags.map((t) => t.id)).toEqual(['tag-1', 'tag-2'])
  })

  it('分頁：next 非 null 時續抓下一頁、合併結果', async () => {
    server.use(
      http.get('*/api/ledger/accounts/', ({ request }) => {
        const page = new URL(request.url).searchParams.get('page') ?? '1'
        return page === '2'
          ? HttpResponse.json({
              count: 2,
              next: null,
              previous: null,
              results: [
                { id: 'acc-2', name: 'B', type: 'bank', balance: '0.00', is_default: false },
              ],
            })
          : HttpResponse.json({
              count: 2,
              next: 'http://x/?page=2',
              previous: null,
              results: [
                { id: 'acc-1', name: 'A', type: 'cash', balance: '0.00', is_default: true },
              ],
            })
      }),
    )
    const store = useReferenceStore()
    await store.ensure()
    expect(store.accounts.map((a) => a.id)).toEqual(['acc-1', 'acc-2'])
  })

  it('暖啟：立即回（0 阻塞）＋背景重抓（每份各 1 發＝3 發）', async () => {
    const store = useReferenceStore()
    await store.ensure() // 冷啟填滿快取

    let hits = 0
    server.use(
      http.get('*/api/ledger/accounts/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
      http.get('*/api/ledger/categories/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
      http.get('*/api/ledger/tags/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )

    await store.ensure() // 暖啟：不 await 背景刷新，但立即 resolve
    expect(hits).toBe(0) // 立即回、未阻塞在網路上

    await store.refresh() // 等背景刷新落地
    expect(hits).toBe(3) // 三份各重抓一發
  })

  it('single-flight：並發 ensure 只發一輪請求', async () => {
    let hits = 0
    server.use(
      http.get('*/api/ledger/accounts/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
      http.get('*/api/ledger/categories/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
      http.get('*/api/ledger/tags/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )
    const store = useReferenceStore()
    await Promise.all([store.ensure(), store.ensure(), store.ensure()])
    expect(hits).toBe(3) // 3 份 × 1 輪，而非 × 3
  })
})

describe('reference store — localStorage 持久化與多用戶隔離', () => {
  it('refresh 成功後 persist 到 ref:{userId}', async () => {
    loginAs('user-a')
    const store = useReferenceStore()
    await store.ensure()

    const cached = JSON.parse(localStorage.getItem('ref:user-a')!)
    expect(cached.accounts.map((a: { id: string }) => a.id)).toEqual(['acc-1', 'acc-2'])
    expect(cached.categories).toHaveLength(3)
    expect(cached.tags).toHaveLength(2)
  })

  it('hydrate：有快取時 ensure 立即可用、不阻塞在網路', async () => {
    loginAs('user-a')
    localStorage.setItem(
      'ref:user-a',
      JSON.stringify({
        accounts: [{ id: 'acc-c', name: '快取帳戶', type: 'cash', balance: '0.00' }],
        categories: [],
        tags: [],
      }),
    )
    let hits = 0
    server.use(
      http.get('*/api/ledger/accounts/', () => {
        hits++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )

    const store = useReferenceStore()
    await store.ensure()
    expect(store.loaded).toBe(true)
    expect(store.accounts.map((a) => a.id)).toEqual(['acc-c']) // 立即回快取值
    expect(hits).toBe(0) // 未阻塞在網路（背景刷新另行落地）
  })

  it('user 隔離：換帳號後讀不到前帳號的快取與記憶體資料', async () => {
    loginAs('user-a')
    const store = useReferenceStore()
    await store.ensure() // A 抓齊＋persist

    // 換 user-b：MSW 回不同資料
    loginAs('user-b')
    server.use(
      http.get('*/api/ledger/accounts/', () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [{ id: 'acc-b', name: 'B 的帳戶', type: 'bank', balance: '0.00' }],
        }),
      ),
    )
    await store.ensure()
    expect(store.accounts.map((a) => a.id)).toEqual(['acc-b']) // 不含 A 的 acc-1/acc-2
    // A 的快取原樣保留在自己的 key 下，B 的落在 B 的 key 下
    expect(JSON.parse(localStorage.getItem('ref:user-a')!).accounts).toHaveLength(2)
    expect(JSON.parse(localStorage.getItem('ref:user-b')!).accounts).toHaveLength(1)
  })

  it('離線冷啟：有快取＋網路死 → 資料照樣可用、不拋錯', async () => {
    loginAs('user-a')
    localStorage.setItem(
      'ref:user-a',
      JSON.stringify({
        accounts: [{ id: 'acc-c', name: '快取帳戶', type: 'cash', balance: '0.00' }],
        categories: [],
        tags: [],
      }),
    )
    server.use(
      http.get('*/api/ledger/accounts/', () => HttpResponse.error()),
      http.get('*/api/ledger/categories/', () => HttpResponse.error()),
      http.get('*/api/ledger/tags/', () => HttpResponse.error()),
    )

    const store = useReferenceStore()
    await store.ensure() // 背景刷新會失敗，但 ensure 本身不得拋
    expect(store.loaded).toBe(true)
    expect(store.accounts.map((a) => a.id)).toEqual(['acc-c'])
  })
})
