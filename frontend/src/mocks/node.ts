import { setupServer } from 'msw/node'
import { handlers } from './handlers'

// Node-side MSW server for Vitest. Wired into the suite via vitest.setup.ts.
export const server = setupServer(...handlers)
