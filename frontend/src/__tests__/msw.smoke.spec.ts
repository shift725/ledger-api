import { describe, it, expect } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'

// De-risks the biggest environment unknown for the auth tests: does MSW
// intercept a relative fetch('/api/...') under happy-dom? If this passes, every
// later auth test can rely on interception; if it can't, it fails loudly here
// in the infra smoke test, not mysteriously deeper in an auth test.
describe('MSW interception (happy-dom smoke)', () => {
  it('intercepts a relative-URL fetch and returns the mocked body', async () => {
    server.use(http.get('*/api/__smoke__', () => HttpResponse.json({ ok: true })))

    const res = await fetch('/api/__smoke__')

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })
  })
})
