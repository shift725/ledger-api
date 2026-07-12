import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './src/mocks/node'

// Unhandled requests error out: a test hitting a real endpoint is a bug, not a
// silent pass-through.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
