<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { toCategoryDoughnut, doughnutChartOptions, type Flow } from '@/lib/reportCharts'
import ChartCanvas from './ChartCanvas.vue'
import MonthFlowControls from './MonthFlowControls.vue'
import Card from '@/components/ui/UiCard.vue'

type CategoryBreakdown = components['schemas']['CategoryBreakdown']

const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const flow = ref<Flow>('expense')

const breakdown = ref<CategoryBreakdown | null>(null)
const loading = ref(false)
const error = ref(false)

async function load() {
  loading.value = true
  error.value = false
  try {
    const { data, error: err } = await api.GET('/api/ledger/reports/summary/by-category/', {
      params: { query: { year: year.value, month: month.value } },
    })
    if (err !== undefined || data === undefined) throw err ?? new Error('empty response')
    breakdown.value = data
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([year, month], load) // 換月重抓；flow 不在依賴＝切收支不抓

const chartData = computed(() =>
  breakdown.value ? toCategoryDoughnut(breakdown.value, flow.value) : { labels: [], datasets: [] },
)
const isEmpty = computed(() => (chartData.value.labels?.length ?? 0) === 0)
const options = doughnutChartOptions()
</script>

<template>
  <Card>
    <MonthFlowControls v-model:year="year" v-model:month="month" v-model:flow="flow" />
    <p v-if="error" class="text-ink-2 py-6 text-center">載入失敗</p>
    <p v-else-if="loading && !breakdown" class="text-ink-2 py-6 text-center">載入中…</p>
    <p v-else-if="isEmpty" class="text-ink-2 py-6 text-center">
      本月無{{ flow === 'expense' ? '支出' : '收入' }}資料
    </p>
    <div v-else class="h-64">
      <ChartCanvas type="doughnut" :data="chartData" :options="options" />
    </div>
  </Card>
</template>
