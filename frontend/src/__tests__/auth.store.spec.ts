import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/auth'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('auth store — login', () => {
  it('stores access, refresh and user on success', async () => {
    const store = useAuthStore()

    await store.login('demo@example.com', 'pw')

    expect(store.access).toBe('access-1')
    expect(store.refresh).toBe('refresh-1')
    expect(store.user).toEqual({
      id: 'user-1',
      username: 'demo',
      email: 'demo@example.com',
      role: 'member',
    })
    expect(store.isAuthenticated).toBe(true)
  })

  it('persists the session to localStorage', async () => {
    const store = useAuthStore()

    await store.login('demo@example.com', 'pw')

    expect(localStorage.getItem('access')).toBe('access-1')
    expect(localStorage.getItem('refresh')).toBe('refresh-1')
    expect(JSON.parse(localStorage.getItem('user')!).username).toBe('demo')
  })

  it('surfaces a 401 as ApiError and leaves the store logged out', async () => {
    server.use(
      http.post('*/api/auth/login/', () =>
        HttpResponse.json({ detail: 'No active account' }, { status: 401 }),
      ),
    )
    const store = useAuthStore()

    await expect(store.login('demo@example.com', 'wrong')).rejects.toBeInstanceOf(ApiError)
    expect(store.isAuthenticated).toBe(false)
  })
})

describe('auth store — register', () => {
  it('logs the user in (authenticated state) on success', async () => {
    const store = useAuthStore()

    await store.register({
      username: 'newbie',
      email: 'new@example.com',
      password: 'pw123456',
      password_confirm: 'pw123456',
    })

    expect(store.isAuthenticated).toBe(true)
    expect(store.access).toBe('access-1')
    expect(store.user?.username).toBe('newbie')
  })
})

describe('auth store — logout', () => {
  it('calls the logout endpoint and clears store + localStorage', async () => {
    let logoutHit = false
    server.use(
      http.post('*/api/auth/logout/', () => {
        logoutHit = true
        return HttpResponse.json({ message: 'ok' })
      }),
    )
    const store = useAuthStore()
    await store.login('demo@example.com', 'pw')

    await store.logout()

    expect(logoutHit).toBe(true)
    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
    expect(localStorage.getItem('access')).toBeNull()
    expect(localStorage.getItem('refresh')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })
})

describe('auth store — reload restoration', () => {
  it('restores tokens and user from localStorage in a fresh store', async () => {
    const first = useAuthStore()
    await first.login('demo@example.com', 'pw')

    // Simulate a reload: fresh Pinia, same localStorage.
    setActivePinia(createPinia())
    const restored = useAuthStore()

    expect(restored.isAuthenticated).toBe(true)
    expect(restored.access).toBe('access-1')
    expect(restored.user?.username).toBe('demo')
  })
})

describe('auth store — refreshAccess single-flight', () => {
  it('fires exactly one refresh request for concurrent callers', async () => {
    let refreshCount = 0
    server.use(
      http.post('*/api/auth/token/refresh/', () => {
        refreshCount += 1
        return HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' })
      }),
    )
    const store = useAuthStore()
    await store.login('demo@example.com', 'pw')

    const [a, b] = await Promise.all([store.refreshAccess(), store.refreshAccess()])

    expect(refreshCount).toBe(1)
    expect(a).toBe('access-2')
    expect(b).toBe('access-2')
    expect(store.access).toBe('access-2')
    expect(store.refresh).toBe('refresh-2')
  })
})
