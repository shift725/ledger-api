import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as auth from '@/api/auth'

type AuthUser = auth.LoginResponse['user']

const ACCESS_KEY = 'access'
const REFRESH_KEY = 'refresh'
const USER_KEY = 'user'

function readUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  // Persisted in localStorage: survives reload without an extra request.
  const access = ref<string | null>(localStorage.getItem(ACCESS_KEY))
  const refresh = ref<string | null>(localStorage.getItem(REFRESH_KEY))
  const user = ref<AuthUser | null>(readUser())
  const isAuthenticated = computed(() => access.value !== null)

  function setSession(a: string, r: string, u: AuthUser) {
    access.value = a
    refresh.value = r
    user.value = u
    localStorage.setItem(ACCESS_KEY, a)
    localStorage.setItem(REFRESH_KEY, r)
    localStorage.setItem(USER_KEY, JSON.stringify(u))
  }

  function clearSession() {
    access.value = null
    refresh.value = null
    user.value = null
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
  }

  async function login(email: string, password: string) {
    const data = await auth.login(email, password)
    setSession(data.access, data.refresh, data.user)
  }

  async function register(input: auth.RegisterInput) {
    const data = await auth.register(input)
    const u = data.user
    setSession(data.tokens.access, data.tokens.refresh, {
      id: u.id,
      username: u.username,
      email: u.email,
      role: u.role ?? 'member',
    })
  }

  async function logout() {
    try {
      if (refresh.value && access.value) await auth.logout(refresh.value, access.value)
    } finally {
      // Clear locally even if the blacklist call fails — the user intends to be
      // logged out; a stuck server shouldn't trap them in a session.
      clearSession()
    }
  }

  // Single-flight refresh. Under ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION,
  // using one refresh token twice gets the second attempt rejected — so concurrent
  // callers must share one in-flight request, not each fire their own.
  let refreshing: Promise<string> | null = null
  function refreshAccess(): Promise<string> {
    if (refreshing) return refreshing
    const token = refresh.value
    if (!token) return Promise.reject(new Error('no refresh token'))
    refreshing = auth
      .refresh(token)
      .then((data) => {
        // Rotation hands back a new refresh token too; persist both.
        access.value = data.access
        refresh.value = data.refresh
        localStorage.setItem(ACCESS_KEY, data.access)
        localStorage.setItem(REFRESH_KEY, data.refresh)
        return data.access
      })
      .finally(() => {
        refreshing = null
      })
    return refreshing
  }

  return {
    access,
    refresh,
    user,
    isAuthenticated,
    login,
    register,
    logout,
    refreshAccess,
    clearSession,
  }
})
