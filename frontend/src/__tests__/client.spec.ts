import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'
import router from '@/router'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'

const ACCOUNTS = '*/api/ledger/accounts/'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  toastMessage.value = ''
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function loginWith(store: ReturnType<typeof useAuthStore>) {
  await store.login('demo@example.com', 'pw') // yields access-1 / refresh-1
}

describe('api client middleware — auth header', () => {
  it('attaches the access token as a Bearer header', async () => {
    let seen: string | null = null
    server.use(
      http.get(ACCOUNTS, ({ request }) => {
        seen = request.headers.get('Authorization')
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
      }),
    )
    const store = useAuthStore()
    await loginWith(store)

    await api.GET('/api/ledger/accounts/')

    expect(seen).toBe('Bearer access-1')
  })
})

describe('api client middleware — 401 refresh + replay', () => {
  it('refreshes on 401 and replays the request with the new token', async () => {
    server.use(
      http.get(ACCOUNTS, ({ request }) => {
        const auth = request.headers.get('Authorization')
        if (auth === 'Bearer access-2') {
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
        }
        return HttpResponse.json({ detail: 'expired' }, { status: 401 })
      }),
    )
    const store = useAuthStore()
    await loginWith(store)

    const { data, error } = await api.GET('/api/ledger/accounts/')

    expect(error).toBeUndefined()
    expect(data).toEqual({ count: 0, next: null, previous: null, results: [] })
    expect(store.access).toBe('access-2') // rotation persisted
  })

  it('fires exactly one refresh for concurrent 401s (single-flight)', async () => {
    let refreshCount = 0
    server.use(
      http.post('*/api/auth/token/refresh/', () => {
        refreshCount += 1
        return HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' })
      }),
      http.get(ACCOUNTS, ({ request }) => {
        const auth = request.headers.get('Authorization')
        if (auth === 'Bearer access-2') {
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
        }
        return HttpResponse.json({ detail: 'expired' }, { status: 401 })
      }),
    )
    const store = useAuthStore()
    await loginWith(store)

    const [a, b] = await Promise.all([
      api.GET('/api/ledger/accounts/'),
      api.GET('/api/ledger/accounts/'),
    ])

    expect(refreshCount).toBe(1)
    expect(a.error).toBeUndefined()
    expect(b.error).toBeUndefined()
  })

  // End-to-end check that a bodied request survives the 401 replay. Note:
  // happy-dom does not consume a passed request's body, so this passes with or
  // without the clone in client.ts — real browsers DO consume it, which is why
  // the clone is kept regardless. Real-browser proof is via manual testing.
  it('preserves the POST body when replaying after refresh', async () => {
    let replayedBody: unknown = null
    server.use(
      http.post(ACCOUNTS, async ({ request }) => {
        const auth = request.headers.get('Authorization')
        if (auth === 'Bearer access-2') {
          replayedBody = await request.json()
          return HttpResponse.json(
            { id: 'a1', name: 'Wallet', type: 'cash', balance: '0.00' },
            { status: 201 },
          )
        }
        return HttpResponse.json({ detail: 'expired' }, { status: 401 })
      }),
    )
    const store = useAuthStore()
    await loginWith(store)

    // The generated Account type is shared between request and response, so its
    // readonly id/balance are still required in the POST body (a codegen wart
    // the create/edit forms will need to address later). Body content is
    // arbitrary here — the middleware under test is body-agnostic; we only
    // check it survives replay.
    const body = { id: 'x', name: 'Wallet', type: 'cash' as const, balance: '0.00' }
    const { error } = await api.POST('/api/ledger/accounts/', { body })

    expect(error).toBeUndefined()
    expect(replayedBody).toEqual(body)
  })
})

describe('api client middleware — 429 節流提示', () => {
  it('429 帶 Retry-After → toast 顯示秒數；回應不吞、照常回傳', async () => {
    server.use(
      http.get(ACCOUNTS, () =>
        HttpResponse.json(
          { detail: 'throttled' },
          { status: 429, headers: { 'Retry-After': '30' } },
        ),
      ),
    )
    const store = useAuthStore()
    await loginWith(store)

    const { response } = await api.GET('/api/ledger/accounts/')

    expect(response.status).toBe(429) // 不吞：呼叫端錯誤態照舊
    expect(toastMessage.value).toContain('30') // 提示含可重試秒數
  })

  it('429 無 Retry-After → 通用「稍後」提示', async () => {
    server.use(
      http.get(ACCOUNTS, () => HttpResponse.json({ detail: 'throttled' }, { status: 429 })),
    )
    const store = useAuthStore()
    await loginWith(store)

    await api.GET('/api/ledger/accounts/')

    expect(toastMessage.value).toContain('稍後')
  })
})

describe('api client middleware — refresh failure', () => {
  it('clears the session and redirects to /login when refresh fails', async () => {
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined)
    server.use(
      http.get(ACCOUNTS, () => HttpResponse.json({ detail: 'expired' }, { status: 401 })),
      http.post('*/api/auth/token/refresh/', () =>
        HttpResponse.json({ detail: 'blacklisted' }, { status: 401 }),
      ),
    )
    const store = useAuthStore()
    await loginWith(store)

    const { response } = await api.GET('/api/ledger/accounts/')

    expect(response.status).toBe(401)
    expect(store.isAuthenticated).toBe(false)
    expect(push).toHaveBeenCalledWith('/login')
  })
})
