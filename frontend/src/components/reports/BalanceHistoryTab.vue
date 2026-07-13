<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { toBalanceHistoryChart, lineChartOptions, balanceRows } from '@/lib/reportCharts'
import ChartCanvas from './ChartCanvas.vue'
import Card from '@/components/ui/UiCard.vue'
import Row from '@/components/ui/UiRow.vue'
import Dot from '@/components/ui/UiDot.vue'
import Amount from '@/components/ui/UiAmount.vue'

type BalanceHistoryAccount = components['schemas']['BalanceHistoryAccount']

const accounts = ref<BalanceHistoryAccount[] | null>(null)
const loading = ref(false)
const error = ref(false)

async function load() {
  loading.value = true
  error.value = false
  try {
    const { data, error: err } = await api.GET('/api/ledger/reports/balance-history/')
    if (err !== undefined || data === undefined) throw err ?? new Error('empty response')
    accounts.value = data
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

// 進頁抓一次：onMounted 只在首次掛載跑；KeepAlive 下切走是 deactivate（不 unmount），
// 切回是 activate（不重掛）→ 不重抓。重整鈕才再打一次（呼應後端 reports-heavy 20/min＋
// 伺服器快取 300s：這支貴，前端不隨 tab 切換揮霍）。
onMounted(load)

const chartData = computed(() => toBalanceHistoryChart(accounts.value ?? []))
const rows = computed(() => balanceRows(accounts.value ?? []))
const isEmpty = computed(() => (chartData.value.labels?.length ?? 0) === 0)
const options = lineChartOptions()
</script>

<template>
  <Card>
    <div class="mb-2 flex items-center justify-between">
      <h2 class="font-medium">餘額走勢</h2>
      <button
        data-test="refresh-balance"
        class="text-brand-text text-sm disabled:opacity-50"
        :disabled="loading"
        @click="load"
      >
        重整
      </button>
    </div>
    <p v-if="error" class="text-ink-2 py-6 text-center">載入失敗</p>
    <p v-else-if="loading && !accounts" class="text-ink-2 py-6 text-center">載入中…</p>
    <p v-else-if="isEmpty" class="text-ink-2 py-6 text-center">尚無餘額資料</p>
    <template v-else>
      <div class="h-64">
        <ChartCanvas type="line" :data="chartData" :options="options" />
      </div>
      <!-- 精確數字表：圖為概略，表給契約字串的精確餘額（各帳戶目前值） -->
      <div class="border-hairline mt-3 border-t pt-2">
        <p class="text-ink-2 mb-1 text-sm">各帳戶目前餘額</p>
        <Row v-for="r in rows" :key="r.label" class="py-1">
          <span class="flex items-center gap-1.5"><Dot :color="r.color" />{{ r.label }}</span>
          <Amount :value="r.balance" />
        </Row>
      </div>
    </template>
  </Card>
</template>
