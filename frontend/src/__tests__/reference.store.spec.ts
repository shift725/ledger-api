import { beforeEach, describe, expect, it, vi } from 'vitest'
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

    // 等背景那輪自己落地。不能拿 refresh() 當同步器——它一律另起一輪，會變成 6 發。
    await vi.waitFor(() => expect(hits).toBe(3)) // 三份各重抓一發
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

describe('reference store — refresh() 的新鮮度', () => {
  it('寫入後的 refresh 抓得到新資料，且進頁那輪晚回也蓋不掉它', async () => {
    // 先讓前面測試沒 await 完的背景刷新落地，再裝自己的 handler——否則下面「進頁那發
    // 已進 handler」的訊號可能是別人的請求觸發的，情境就沒建立起來（實測過，會假綠）。
    await new Promise((resolve) => setTimeout(resolve, 100))

    let release!: () => void
    let firstEntered!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    const entered = new Promise<void>((resolve) => (firstEntered = resolve))
    let written = false
    server.use(
      // 「寫入」之前發出的抓取一律押住且內容停在寫入前，之後發出的才看得到新帳戶——
      // 兩份內容必須不同，否則有沒有共用在途請求都長一樣，這個 bug 在測試裡不可見。
      // 判斷依據刻意用寫入與否而非「第幾發」：其他測試沒 await 完的背景刷新也會打到
      // 這個端點，數次數會被它們汙染（實測過，會假綠）。
      http.get('*/api/ledger/accounts/', async () => {
        if (!written) {
          firstEntered()
          await held
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
        }
        return HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 'acc-new',
              name: '剛建立的帳戶',
              type: 'cash',
              balance: '0.00',
              is_default: false,
            },
          ],
        })
      }),
    )

    const store = useReferenceStore()
    const mounting = store.ensure() // 進頁抓取
    await entered // 它真的進了 handler、卡在慢網路上，情境才算成立
    written = true // 使用者建立帳戶，後端已寫入
    const afterWrite = store.refresh() // 寫入成功後重抓

    try {
      // 共用在途抓取的話，這裡永遠等不到新帳戶——就是使用者看到的「存好了卻不在清單裡」。
      await vi.waitFor(() => expect(store.accounts.map((a) => a.id)).toEqual(['acc-new']))
      await afterWrite

      release() // 進頁那輪（內容已過期）現在才回來
      await mounting
      expect(store.accounts.map((a) => a.id)).toEqual(['acc-new']) // 舊結果不得覆蓋新的
    } finally {
      release()
      await Promise.allSettled([mounting, afterWrite]) // 別把在途請求留給下一支測試
    }
  })
})
