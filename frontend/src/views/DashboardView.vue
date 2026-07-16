<script setup lang="ts">
import { computed, onMounted, reactive } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { loadErrorText } from '@/lib/online'
import { createDotAssigner } from '@/lib/dots'
import { formatAmount } from '@/lib/format'
import Card from '@/components/ui/UiCard.vue'
import Row from '@/components/ui/UiRow.vue'
import Amount from '@/components/ui/UiAmount.vue'
import Dot from '@/components/ui/UiDot.vue'
import ProgressBar from '@/components/ui/UiProgressBar.vue'
import Badge from '@/components/ui/UiBadge.vue'

type MonthSummary = components['schemas']['MonthSummary']
type TodaySummary = components['schemas']['TodaySummary']
type BalanceOverview = components['schemas']['BalanceOverview']
type SavingsGoalStatus = components['schemas']['SavingsGoalStatus']
type Transaction = components['schemas']['Transaction']

// openapi-fetch 把非 2xx 放進 error 欄位；收斂成「拿到資料或拋錯」給區塊態用。
async function getJson<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error } = await promise
  if (error !== undefined || data === undefined) throw error ?? new Error('empty response')
  return data
}

// 區塊級三態：每區塊獨立抓、獨立倒，一支報表掛不拖垮整個 dashboard。
interface Block<T> {
  data: T | null
  error: boolean
}
function useBlock<T>(fetcher: () => Promise<T>): Block<T> {
  const state = reactive({ data: null, error: false }) as Block<T>
  onMounted(async () => {
    try {
      state.data = await fetcher()
    } catch {
      state.error = true
    }
  })
  return state
}

const now = new Date()
const headerDate = `${now.getFullYear()}年${now.getMonth() + 1}月`

const summary = useBlock<MonthSummary>(() => getJson(api.GET('/api/ledger/reports/summary/')))
const today = useBlock<TodaySummary>(() => getJson(api.GET('/api/ledger/reports/today/')))
const balance = useBlock<BalanceOverview>(() => getJson(api.GET('/api/ledger/reports/balance/')))
// 帶 month＝月度、省略＝年度（契約語意）；兩發並行，一發失敗＝整塊倒
const goals = useBlock<{ monthly: SavingsGoalStatus; yearly: SavingsGoalStatus }>(async () => {
  const [monthly, yearly] = await Promise.all([
    getJson(
      api.GET('/api/ledger/reports/savings-goal-status/', {
        params: { query: { month: now.getMonth() + 1, year: now.getFullYear() } },
      }),
    ),
    getJson(api.GET('/api/ledger/reports/savings-goal-status/')),
  ])
  return { monthly, yearly }
})
const recent = useBlock<Transaction[]>(async () => {
  const page = await getJson(
    api.GET('/api/ledger/transactions/', { params: { query: { page: 1 } } }),
  )
  return page.results.slice(0, 5)
})

// 淨額中性色帶符號（正值補 +；負號隨字串），不走語意紅綠——方向已由收支列表達
const netDisplay = computed(() => {
  const net = summary.data?.net
  if (net === undefined || net === null) return ''
  return (Number(net) > 0 ? '+' : '') + formatAmount(net)
})

// 色點：每「渲染範圍 × 資源型別」一個 assigner
const accountDots = computed(() => {
  const assign = createDotAssigner()
  return new Map((balance.data?.accounts ?? []).map((a) => [a.id, assign(a.id)]))
})
const categoryDots = computed(() => {
  const assign = createDotAssigner()
  const dots = new Map<string, string>()
  for (const txn of recent.data ?? []) {
    if (txn.category) dots.set(txn.category, assign(txn.category))
  }
  return dots
})

// 顯示層 fallback：name → category_name → 未命名
function displayName(txn: Transaction): string {
  return txn.name || txn.category_name || '未命名'
}

function goalPercent(goal: SavingsGoalStatus): number {
  const target = Number(goal.goal_amount)
  if (!target) return 0
  return Math.max(0, Math.round((Number(goal.actual_net) / target) * 100))
}
</script>

<template>
  <header class="mb-3.5 flex items-baseline justify-between">
    <h1 class="text-xl font-medium">總覽</h1>
    <span class="text-ink-2">{{ headerDate }}</span>
  </header>

  <div class="flex flex-col gap-2.5">
    <!-- ① 本月摘要 ← reports/summary/（當年當月） -->
    <Card data-test="block-summary">
      <p v-if="summary.error" class="text-ink-2">{{ loadErrorText }}</p>
      <template v-else-if="summary.data">
        <Row>
          <span class="text-ink-2">本月收入</span>
          <Amount :value="summary.data.income" type="income" />
        </Row>
        <Row class="mt-2">
          <span class="text-ink-2">本月支出</span>
          <Amount :value="summary.data.expense" type="expense" />
        </Row>
        <Row class="border-hairline mt-2.5 border-t pt-2.5">
          <span>本月淨額</span>
          <span class="font-medium">{{ netDisplay }}</span>
        </Row>
      </template>
      <p v-else class="text-ink-2">載入中…</p>
    </Card>

    <!-- ② 今日收支 ← reports/today/ -->
    <Card data-test="block-today">
      <p v-if="today.error" class="text-ink-2">{{ loadErrorText }}</p>
      <template v-else-if="today.data">
        <Row>
          <span class="text-ink-2">今日支出</span>
          <Amount :value="today.data.expense" type="expense" />
        </Row>
        <Row class="mt-2">
          <span class="text-ink-2">今日收入</span>
          <Amount data-test="today-income" :value="today.data.income" type="income" />
        </Row>
      </template>
      <p v-else class="text-ink-2">載入中…</p>
    </Card>

    <!-- ③ 帳戶餘額 ← reports/balance/（一發拿齊，不打 accounts/） -->
    <Card data-test="block-balance">
      <p v-if="balance.error" class="text-ink-2">{{ loadErrorText }}</p>
      <template v-else-if="balance.data">
        <Row>
          <span class="text-ink-2">總資產</span>
          <span class="font-medium">{{ formatAmount(balance.data.total_balance) }}</span>
        </Row>
        <Row v-for="account in balance.data.accounts" :key="account.id" class="mt-2">
          <span class="flex items-center gap-1.5">
            <Dot :color="accountDots.get(account.id)!" />{{ account.name }}
          </span>
          <Amount :value="account.balance" />
        </Row>
      </template>
      <p v-else class="text-ink-2">載入中…</p>
    </Card>

    <!-- ④ 儲蓄目標 ← savings-goal-status（本月＋年度各一發） -->
    <Card data-test="block-goals">
      <p v-if="goals.error" class="text-ink-2">{{ loadErrorText }}</p>
      <template v-else-if="goals.data">
        <template
          v-for="goal in [
            { label: '本月儲蓄目標', status: goals.data.monthly },
            { label: '年度儲蓄目標', status: goals.data.yearly },
          ]"
          :key="goal.label"
        >
          <Row :class="goal.label.startsWith('年度') ? 'mt-3' : ''">
            <span class="text-ink-2">{{ goal.label }}</span>
            <span v-if="goal.status.goal_amount !== null" class="text-brand-text font-medium">
              {{ goalPercent(goal.status) }}%
            </span>
            <RouterLink v-else to="/settings/goals" class="text-brand-text text-sm font-medium">
              尚未設定，前往設定
            </RouterLink>
          </Row>
          <ProgressBar
            v-if="goal.status.goal_amount !== null"
            class="mt-1.5"
            :percent="goalPercent(goal.status)"
          />
        </template>
      </template>
      <p v-else class="text-ink-2">載入中…</p>
    </Card>

    <!-- ⑤ 最近交易 ← transactions/?page=1 取前 5 -->
    <Card data-test="block-recent" class="py-1">
      <p v-if="recent.error" class="text-ink-2 py-2.5">{{ loadErrorText }}</p>
      <template v-else-if="recent.data">
        <Row
          v-for="txn in recent.data"
          :key="txn.id"
          class="border-hairline border-b py-2.5 last:border-b-0"
        >
          <span class="flex min-w-0 items-center gap-1.5">
            <Dot v-if="txn.category" :color="categoryDots.get(txn.category)!" />
            <span class="truncate">{{ displayName(txn) }}</span>
            <span v-if="txn.name && txn.category_name" class="text-ink-2 shrink-0">
              · {{ txn.category_name }}
            </span>
            <Badge v-if="txn.source_rule">自動</Badge>
          </span>
          <Amount :value="txn.amount" :type="txn.type" signed />
        </Row>
        <div class="py-2.5 text-right">
          <RouterLink to="/transactions" class="text-brand-text text-sm font-medium">
            查看全部
          </RouterLink>
        </div>
      </template>
      <p v-else class="text-ink-2 py-2.5">載入中…</p>
    </Card>
  </div>
</template>
