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

  // ── dashboard 五區塊罐頭 ──
  http.get('*/api/ledger/reports/summary/', () =>
    HttpResponse.json({
      year: 2026,
      month: 7,
      income: '52000.00',
      expense: '31240.00',
      net: '20760.00',
    }),
  ),
  http.get('*/api/ledger/reports/today/', () =>
    HttpResponse.json({ date: '2026-07-12', expense: '340.00', income: '0.00', net: '-340.00' }),
  ),
  http.get('*/api/ledger/reports/balance/', () =>
    HttpResponse.json({
      total_balance: '248350.00',
      accounts: [
        { id: 'acc-1', name: '現金', type: 'cash', balance: '12350.00' },
        { id: 'acc-2', name: '台新銀行', type: 'bank', balance: '236000.00' },
      ],
    }),
  ),
  // 帶 month＝月度、省略＝年度（契約語意）
  http.get('*/api/ledger/reports/savings-goal-status/', ({ request }) => {
    const month = new URL(request.url).searchParams.get('month')
    return HttpResponse.json(
      month
        ? {
            period_type: 'monthly',
            year: 2026,
            month: Number(month),
            goal_amount: '20000.00',
            actual_net: '13600.00',
            difference: '-6400.00',
            achieved: false,
          }
        : {
            period_type: 'yearly',
            year: 2026,
            month: null,
            goal_amount: '240000.00',
            actual_net: '98400.00',
            difference: '-141600.00',
            achieved: false,
          },
    )
  }),
  http.get('*/api/ledger/transactions/', () =>
    HttpResponse.json({
      count: 4,
      next: null,
      previous: null,
      results: [
        {
          id: 't1',
          account: 'acc-1',
          account_name: '現金',
          category: 'cat-food',
          category_name: '餐飲',
          amount: '120.00',
          type: 'expense',
          name: '午餐',
          description: '',
          occurred_at: '2026-07-12T12:00:00+08:00',
          tags: [],
          tag_names: [],
          source_rule: null,
        },
        {
          id: 't2',
          account: 'acc-2',
          account_name: '台新銀行',
          category: 'cat-home',
          category_name: '居住',
          amount: '15000.00',
          type: 'expense',
          name: '房租',
          description: '',
          occurred_at: '2026-07-05T00:00:00+08:00',
          tags: [],
          tag_names: [],
          source_rule: 'rule-1',
        },
        {
          id: 't3',
          account: 'acc-2',
          account_name: '台新銀行',
          category: 'cat-salary',
          category_name: '薪水',
          amount: '52000.00',
          type: 'income',
          name: '',
          description: '',
          occurred_at: '2026-07-01T09:00:00+08:00',
          tags: [],
          tag_names: [],
          source_rule: null,
        },
        {
          id: 't4',
          account: 'acc-1',
          account_name: '現金',
          category: null,
          category_name: null,
          amount: '60.00',
          type: 'expense',
          name: '',
          description: '',
          occurred_at: '2026-06-30T08:00:00+08:00',
          tags: [],
          tag_names: [],
          source_rule: null,
        },
      ],
    }),
  ),
]
