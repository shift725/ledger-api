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
  // 每帳戶逐月餘額（起月不同→前端聯集軸＋前導 null）
  http.get('*/api/ledger/reports/balance-history/', () =>
    HttpResponse.json([
      {
        account_id: 'acc-1',
        account_name: '現金',
        months: [
          { month: '2026-05', balance: '5000.00' },
          { month: '2026-06', balance: '8000.00' },
          { month: '2026-07', balance: '12350.00' },
        ],
      },
      {
        account_id: 'acc-2',
        account_name: '台新銀行',
        months: [
          { month: '2026-06', balance: '200000.00' },
          { month: '2026-07', balance: '236000.00' },
        ],
      },
    ]),
  ),
  // 分類收支（單值 FK，含未分類 null 桶）；收支雙值供前端切換
  http.get('*/api/ledger/reports/summary/by-category/', () =>
    HttpResponse.json({
      year: 2026,
      month: 7,
      categories: [
        { category_id: 'cat-food', category_name: '餐飲', income: '0.00', expense: '8200.00' },
        { category_id: 'cat-home', category_name: '居住', income: '0.00', expense: '15000.00' },
        { category_id: 'cat-salary', category_name: '薪水', income: '52000.00', expense: '0.00' },
        { category_id: null, category_name: null, income: '0.00', expense: '340.00' },
      ],
    }),
  ),
  // 標籤收支（M2M 可重疊）；收支雙值供前端切換
  http.get('*/api/ledger/reports/summary/by-tag/', () =>
    HttpResponse.json({
      year: 2026,
      month: 7,
      tags: [
        { tag_id: 'tag-1', tag_name: '固定支出', income: '0.00', expense: '23000.00' },
        { tag_id: 'tag-2', tag_name: '訂閱', income: '0.00', expense: '460.00' },
      ],
    }),
  ),
  // ── reference 清單（帳戶/分類/標籤）：id 與交易罐頭對齊 ──
  http.get('*/api/ledger/accounts/', () =>
    HttpResponse.json({
      count: 2,
      next: null,
      previous: null,
      results: [
        { id: 'acc-1', name: '現金', type: 'cash', balance: '12350.00', is_default: true },
        { id: 'acc-2', name: '台新銀行', type: 'bank', balance: '236000.00', is_default: false },
      ],
    }),
  ),
  http.get('*/api/ledger/categories/', () =>
    HttpResponse.json({
      count: 3,
      next: null,
      previous: null,
      results: [
        { id: 'cat-food', name: '餐飲', description: '' },
        { id: 'cat-home', name: '居住', description: '' },
        { id: 'cat-salary', name: '薪水', description: '' },
      ],
    }),
  ),
  http.get('*/api/ledger/tags/', () =>
    HttpResponse.json({
      count: 2,
      next: null,
      previous: null,
      results: [
        { id: 'tag-1', name: '固定支出', description: '' },
        { id: 'tag-2', name: '訂閱', description: '' },
      ],
    }),
  ),
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
