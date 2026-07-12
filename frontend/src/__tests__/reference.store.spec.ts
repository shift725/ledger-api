import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'
import { useReferenceStore } from '@/stores/reference'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

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
