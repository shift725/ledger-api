import { http, HttpResponse } from 'msw'
import type { RequestHandler } from 'msw'

// Happy-path auth handlers. Tests override per-case with server.use() for error
// and counting scenarios (afterEach resetHandlers restores these defaults).
//
// URL matchers use the `*/api/...` wildcard prefix: under happy-dom a relative
// fetch('/api/...') resolves against the test-page origin, so matching any
// origin keeps handlers independent of that origin.
export const handlers: RequestHandler[] = [
  http.post('*/api/auth/login/', async ({ request }) => {
    const { email } = (await request.json()) as { email: string; password: string }
    return HttpResponse.json({
      access: 'access-1',
      refresh: 'refresh-1',
      user: { id: 'user-1', username: 'demo', email, role: 'member' },
    })
  }),
  http.post('*/api/auth/register/', async ({ request }) => {
    const { username, email } = (await request.json()) as { username: string; email: string }
    return HttpResponse.json(
      {
        message: '註冊成功',
        user: { id: 'user-1', username, email, role: 'member', created_at: '2026-07-12T00:00:00Z' },
        tokens: { access: 'access-1', refresh: 'refresh-1' },
      },
      { status: 201 },
    )
  }),
  http.post('*/api/auth/token/refresh/', () =>
    HttpResponse.json({ access: 'access-2', refresh: 'refresh-2' }),
  ),
  http.post('*/api/auth/logout/', () => HttpResponse.json({ message: '登出成功' })),
]
