import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'
import { enqueue, queueCount, replay } from '@/lib/offlineQueue'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  toastMessage.value = ''
})

function loginAs(id: string) {
  const auth = useAuthStore()
  auth.user = { id, username: id, email: `${id}@x.tw`, role: 'member' }
  auth.access = 'test-access'
}

const txn = {
  account: 'acc-1',
  amount: '100.00',
  type: 'expense' as const,
  occurred_at: '2026-07-15T10:00:00.000Z',
  category: null,
  tags: [],
  name: '',
  description: '',
}

function stored(userId: string): unknown[] {
  return JSON.parse(localStorage.getItem(`queue:${userId}`) ?? '[]')
}

describe('offlineQueue — enqueue', () => {
  it('入隊寫進 queue:{userId}、queueCount 反映', () => {
    loginAs('user-a')
    enqueue(txn)
    enqueue({ ...txn, amount: '50.00' })
    expect(stored('user-a')).toHaveLength(2)
    expect(queueCount.value).toBe(2)
  })

  it('未登入不入隊（無 key 可組）', () => {
    enqueue(txn)
    expect(localStorage.length).toBe(0)
  })
})

describe('offlineQueue — replay', () => {
  it('成功：全部補送、佇列清空、reference 背景刷新被觸發', async () => {
    loginAs('user-a')
    enqueue(txn)
    enqueue({ ...txn, amount: '50.00' })

    let posts = 0
    let refGets = 0
    server.use(
      http.post('*/api/ledger/transactions/', () => {
        posts++
        return HttpResponse.json({ id: `t-${posts}`, ...txn }, { status: 201 })
      }),
      http.get('*/api/ledger/accounts/', () => {
        refGets++
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )

    await replay()
    expect(posts).toBe(2)
    expect(stored('user-a')).toHaveLength(0)
    expect(queueCount.value).toBe(0)
    expect(toastMessage.value).toContain('已補送 2 筆')

    await Promise.resolve() // 讓背景 refresh 的請求出得去
    await new Promise((r) => setTimeout(r, 20))
    expect(refGets).toBeGreaterThan(0)
  })

  it('4xx 業務錯（資料已失效）：出隊不卡佇列、提示失效', async () => {
    loginAs('user-a')
    enqueue(txn)
    server.use(
      http.post('*/api/ledger/transactions/', () =>
        HttpResponse.json({ account: ['無效'] }, { status: 400 }),
      ),
    )

    await replay()
    expect(stored('user-a')).toHaveLength(0) // 毒丸不留
    expect(toastMessage.value).toContain('已失效')
  })

  it('網路錯：整批留在佇列，下次再試', async () => {
    loginAs('user-a')
    enqueue(txn)
    server.use(http.post('*/api/ledger/transactions/', () => HttpResponse.error()))

    await replay()
    expect(stored('user-a')).toHaveLength(1)
    expect(queueCount.value).toBe(1)
  })

  it('5xx 伺服器錯：留隊、中止本輪（不對壞伺服器連發）', async () => {
    loginAs('user-a')
    enqueue(txn)
    enqueue({ ...txn, amount: '50.00' })
    let posts = 0
    server.use(
      http.post('*/api/ledger/transactions/', () => {
        posts++
        return HttpResponse.json({ detail: 'boom' }, { status: 500 })
      }),
    )

    await replay()
    expect(posts).toBe(1) // 第一筆失敗即停
    expect(stored('user-a')).toHaveLength(2)
  })

  it('single-flight：並發 replay 只跑一輪', async () => {
    loginAs('user-a')
    enqueue(txn)
    let posts = 0
    server.use(
      http.post('*/api/ledger/transactions/', () => {
        posts++
        return HttpResponse.json({ id: 't-1', ...txn }, { status: 201 })
      }),
    )

    await Promise.all([replay(), replay(), replay()])
    expect(posts).toBe(1)
  })
})
