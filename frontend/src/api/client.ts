import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

// Typed client for business endpoints (the ones whose schema is accurate). Auth
// endpoints bypass this and use plain fetch in api/auth.ts — see that file.
//
// This module imports the store and router, and both are used only inside the
// callbacks below (never at module top level), so the ESM import cycle
// client -> store -> api/auth and client -> router -> store stays safe. Moving
// either call to top level would execute mid-initialization and break.

// A request's body is a one-shot stream: fetch consumes it, so a 401'd request
// can't be re-sent as-is. We clone each request before it goes out and replay
// the clone (whose body is intact) after refreshing. Keyed by openapi-fetch's
// per-request id, which links onRequest and onResponse.
const replayClones = new Map<string, Request>()

const authMiddleware: Middleware = {
  onRequest({ request, id }) {
    const { access } = useAuthStore()
    if (access) request.headers.set('Authorization', `Bearer ${access}`)
    replayClones.set(id, request.clone())
    return request
  },

  async onResponse({ response, id }) {
    const retry = replayClones.get(id)
    replayClones.delete(id)

    if (response.status !== 401 || !retry) return response

    const store = useAuthStore()
    let access: string
    try {
      access = await store.refreshAccess()
    } catch {
      // Refresh token is dead (expired or blacklisted): the session is over.
      store.clearSession()
      await router.push('/login')
      return response
    }

    retry.headers.set('Authorization', `Bearer ${access}`)
    return fetch(retry)
  },
}

export const api = createClient<paths>()
api.use(authMiddleware)
