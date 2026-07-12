import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { RouteLocationNormalized } from 'vue-router'
import { authGuard } from '@/router'
import { useAuthStore } from '@/stores/auth'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

function route(meta: Record<string, unknown>, fullPath = '/reports'): RouteLocationNormalized {
  return { meta, fullPath } as RouteLocationNormalized
}

function authenticate() {
  useAuthStore().access = 'token'
}

describe('authGuard', () => {
  it('redirects an unauthenticated user off a protected route, keeping the destination', () => {
    expect(authGuard(route({ requiresAuth: true }, '/reports'))).toEqual({
      path: '/login',
      query: { redirect: '/reports' },
    })
  })

  it('lets an authenticated user into a protected route', () => {
    authenticate()
    expect(authGuard(route({ requiresAuth: true }))).toBe(true)
  })

  it('redirects an authenticated user off a guest-only route', () => {
    authenticate()
    expect(authGuard(route({ guestOnly: true }))).toEqual({ path: '/' })
  })

  it('lets a guest into a guest-only route', () => {
    expect(authGuard(route({ guestOnly: true }))).toBe(true)
  })
})
