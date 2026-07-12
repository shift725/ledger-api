<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { emptyFilterState, parseQuery, toApiParams, toQuery, ORDERINGS } from '@/lib/txnFilters'
import { useReferenceStore } from '@/stores/reference'
import { createDotAssigner } from '@/lib/dots'
import Card from '@/components/ui/UiCard.vue'
import Row from '@/components/ui/UiRow.vue'
import Amount from '@/components/ui/UiAmount.vue'
import Dot from '@/components/ui/UiDot.vue'
import Badge from '@/components/ui/UiBadge.vue'

type Transaction = components['schemas']['Transaction']

const PAGE_SIZE = 20 // 後端分頁固定每頁 20 筆

const route = useRoute()
const router = useRouter()
const reference = useReferenceStore()

const filters = reactive(emptyFilterState())
const panelOpen = ref(false) // 手機收合；桌面 CSS 恆展開

const list = ref<Transaction[]>([])
const count = ref(0)
const next = ref<string | null>(null)
const page = ref(1)
const loading = ref(false)
const error = ref(false)

const ORDER_LABELS: Record<(typeof ORDERINGS)[number], string> = {
  '-occurred_at': '日期（新→舊）',
  occurred_at: '日期（舊→新）',
  '-amount': '金額（高→低）',
  amount: '金額（低→高）',
}

// 桌面頁碼 vs 手機無限捲動：同一資料層，差在 UI 與「替換 vs 附加」。
const isDesktop = ref(window.matchMedia?.('(min-width: 768px)').matches ?? true)
let mql: MediaQueryList | undefined
function onMql(e: MediaQueryListEvent) {
  isDesktop.value = e.matches
}

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / PAGE_SIZE)))
const empty = computed(() => !loading.value && !error.value && list.value.length === 0)

const categoryDots = computed(() => {
  const assign = createDotAssigner()
  const dots = new Map<string, string>()
  for (const txn of list.value) if (txn.category) dots.set(txn.category, assign(txn.category))
  return dots
})

function displayName(txn: Transaction): string {
  return txn.name || txn.category_name || '未命名'
}
function displayDate(iso: string): string {
  return new Date(iso).toLocaleDateString('sv-SE') // sv-SE ＝ YYYY-MM-DD
}

async function load(target: number, append = false) {
  loading.value = true
  error.value = false
  try {
    const { data, error: err } = await api.GET('/api/ledger/transactions/', {
      params: { query: toApiParams(filters, target) },
      // 後端 UUIDInFilter 拆逗號、重複參數只認最後一個 → 陣列必須 CSV 單值。
      // openapi-fetch 預設 explode:true（重複參數），此處覆寫成 CSV。
      querySerializer: { array: { style: 'form', explode: false } },
    })
    if (err !== undefined || data === undefined) throw err ?? new Error('empty response')
    list.value = append ? [...list.value, ...data.results] : data.results
    count.value = data.count
    next.value = data.next ?? null
    page.value = target
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function loadMore() {
  if (next.value && !loading.value) load(page.value + 1, true) // 手機：附加
}

// URL query ＝真相：使用者改動只寫 URL（replace，不堆歷史），watcher 再解析回 filters＋載第一頁。
// 單向流：編輯 → URL → 重載，避免雙寫互相觸發。
function apply() {
  router.replace({ query: toQuery(filters) })
}
watch(
  () => route.query,
  (q) => {
    Object.assign(filters, parseQuery(q))
    load(1)
  },
  { immediate: true },
)

function toggleTag(kind: 'tagsAny' | 'tagsAll', id: string) {
  const arr = filters[kind]
  const i = arr.indexOf(id)
  if (i === -1) arr.push(id)
  else arr.splice(i, 1)
  apply()
}

const nameOf = (list: { id: string; name: string }[], id: string) =>
  list.find((x) => x.id === id)?.name ?? id

// 生效條件 → chips（每個可單獨移除；tags 逐值一顆）。
const chips = computed(() => {
  const c: { label: string; clear: () => void }[] = []
  const clr = (f: () => void) => () => {
    f()
    apply()
  }
  if (filters.search)
    c.push({ label: `搜尋：${filters.search}`, clear: clr(() => (filters.search = '')) })
  if (filters.type)
    c.push({
      label: `類型：${filters.type === 'income' ? '收入' : '支出'}`,
      clear: clr(() => (filters.type = '')),
    })
  if (filters.account)
    c.push({
      label: `帳戶：${nameOf(reference.accounts, filters.account)}`,
      clear: clr(() => (filters.account = '')),
    })
  if (filters.category)
    c.push({
      label: `分類：${nameOf(reference.categories, filters.category)}`,
      clear: clr(() => (filters.category = '')),
    })
  if (filters.amountMin)
    c.push({ label: `≥ ${filters.amountMin}`, clear: clr(() => (filters.amountMin = '')) })
  if (filters.amountMax)
    c.push({ label: `≤ ${filters.amountMax}`, clear: clr(() => (filters.amountMax = '')) })
  if (filters.dateFrom)
    c.push({ label: `從 ${filters.dateFrom}`, clear: clr(() => (filters.dateFrom = '')) })
  if (filters.dateTo)
    c.push({ label: `到 ${filters.dateTo}`, clear: clr(() => (filters.dateTo = '')) })
  for (const id of filters.tagsAny)
    c.push({
      label: `標籤(任一)：${nameOf(reference.tags, id)}`,
      clear: () => toggleTag('tagsAny', id),
    })
  for (const id of filters.tagsAll)
    c.push({
      label: `標籤(全部)：${nameOf(reference.tags, id)}`,
      clear: () => toggleTag('tagsAll', id),
    })
  return c
})

const sentinel = ref<HTMLElement | null>(null)
let io: IntersectionObserver | undefined

onMounted(() => {
  reference.ensure() // 過濾選單用；SWR 快取先用、背景刷新
  mql = window.matchMedia?.('(min-width: 768px)')
  mql?.addEventListener?.('change', onMql)
  io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) loadMore()
  })
  if (sentinel.value) io.observe(sentinel.value)
})
onBeforeUnmount(() => {
  mql?.removeEventListener?.('change', onMql)
  io?.disconnect()
})
</script>

<template>
  <header class="mb-3.5 flex items-baseline justify-between">
    <h1 class="text-xl font-medium">交易</h1>
    <span v-if="count" class="text-ink-2 text-sm">{{ count }} 筆</span>
  </header>

  <!-- 搜尋＋排序＋展開過濾 -->
  <div class="mb-2.5 flex gap-2">
    <input
      data-test="filter-search"
      :value="filters.search"
      type="search"
      placeholder="搜尋名稱或說明"
      class="border-hairline min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm"
      @change="
        (e) => {
          filters.search = (e.target as HTMLInputElement).value
          apply()
        }
      "
    />
    <select
      v-model="filters.ordering"
      class="border-hairline rounded-lg border px-2 py-2 text-sm"
      @change="apply"
    >
      <option v-for="o in ORDERINGS" :key="o" :value="o">{{ ORDER_LABELS[o] }}</option>
    </select>
    <button
      class="border-hairline rounded-lg border px-3 py-2 text-sm md:hidden"
      @click="panelOpen = !panelOpen"
    >
      過濾
    </button>
  </div>

  <!-- 過濾面板：手機收合、桌面平鋪 -->
  <Card v-show="panelOpen || isDesktop" class="mb-2.5 flex flex-col gap-2.5">
    <div class="flex gap-2">
      <select
        v-model="filters.type"
        data-test="filter-type"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      >
        <option value="">全部類型</option>
        <option value="income">收入</option>
        <option value="expense">支出</option>
      </select>
      <select
        v-model="filters.account"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      >
        <option value="">全部帳戶</option>
        <option v-for="a in reference.accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
      </select>
      <select
        v-model="filters.category"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      >
        <option value="">全部分類</option>
        <option v-for="c in reference.categories" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
    </div>
    <div class="flex gap-2">
      <input
        v-model.lazy="filters.amountMin"
        inputmode="decimal"
        placeholder="金額最小"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      />
      <input
        v-model.lazy="filters.amountMax"
        inputmode="decimal"
        placeholder="金額最大"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      />
      <input
        v-model="filters.dateFrom"
        type="date"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      />
      <input
        v-model="filters.dateTo"
        type="date"
        class="border-hairline min-w-0 flex-1 rounded-lg border px-2 py-2 text-sm"
        @change="apply"
      />
    </div>
    <div v-if="reference.tags.length" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span class="text-ink-2">標籤(任一)：</span>
      <label v-for="t in reference.tags" :key="'any-' + t.id" class="flex items-center gap-1">
        <input
          type="checkbox"
          :checked="filters.tagsAny.includes(t.id)"
          @change="toggleTag('tagsAny', t.id)"
        />{{ t.name }}
      </label>
    </div>
    <div v-if="reference.tags.length" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span class="text-ink-2">標籤(全部)：</span>
      <label v-for="t in reference.tags" :key="'all-' + t.id" class="flex items-center gap-1">
        <input
          type="checkbox"
          :checked="filters.tagsAll.includes(t.id)"
          @change="toggleTag('tagsAll', t.id)"
        />{{ t.name }}
      </label>
    </div>
  </Card>

  <!-- 生效條件 chips -->
  <div v-if="chips.length" class="mb-2.5 flex flex-wrap gap-1.5">
    <span
      v-for="chip in chips"
      :key="chip.label"
      class="bg-brand-tint text-brand-text flex items-center gap-1 rounded-full px-2.5 py-1 text-sm"
    >
      {{ chip.label }}
      <button data-test="chip-remove" class="text-base leading-none" @click="chip.clear()">
        ×
      </button>
    </span>
  </div>

  <Card class="py-1">
    <p v-if="error" class="text-ink-2 py-2.5">載入失敗</p>
    <p v-else-if="empty" class="text-ink-2 py-6 text-center">沒有交易</p>
    <template v-else>
      <RouterLink
        v-for="txn in list"
        :key="txn.id"
        :to="`/transactions/${txn.id}`"
        class="border-hairline block border-b py-2.5 last:border-b-0"
      >
        <Row>
          <span class="flex min-w-0 items-center gap-1.5">
            <Dot v-if="txn.category" :color="categoryDots.get(txn.category)!" />
            <span class="truncate">{{ displayName(txn) }}</span>
            <Badge v-if="txn.source_rule">自動</Badge>
          </span>
          <Amount :value="txn.amount" :type="txn.type" signed />
        </Row>
        <Row class="text-ink-2 mt-0.5 text-sm">
          <span>{{ txn.account_name }}</span>
          <span>{{ displayDate(txn.occurred_at ?? '') }}</span>
        </Row>
      </RouterLink>

      <!-- 手機：sentinel 進視窗續抓 -->
      <div v-if="!isDesktop" ref="sentinel" class="h-1"></div>
      <p v-if="!isDesktop && loading" class="text-ink-2 py-2.5 text-center text-sm">載入中…</p>
    </template>
  </Card>

  <!-- 桌面：頁碼 -->
  <nav v-if="isDesktop && totalPages > 1" class="mt-3 flex justify-center gap-1">
    <button
      v-for="n in totalPages"
      :key="n"
      class="min-w-8 rounded-md px-2 py-1 text-sm"
      :class="n === page ? 'bg-brand-tint text-brand-text font-medium' : 'text-ink-2'"
      :disabled="n === page"
      @click="load(n, false)"
    >
      {{ n }}
    </button>
  </nav>
</template>
