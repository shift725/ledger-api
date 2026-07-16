<script setup lang="ts">
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { loadErrorText } from '@/lib/online'
import type { components } from '@/api/schema'
import { formatAmount } from '@/lib/format'
import Card from '@/components/ui/UiCard.vue'
import Row from '@/components/ui/UiRow.vue'
import Amount from '@/components/ui/UiAmount.vue'

type RangeSummary = components['schemas']['RangeSummary']

const start = ref('')
const end = ref('')
const result = ref<RangeSummary | null>(null)
const loading = ref(false)
const error = ref(false)

// 前端擋：兩端皆須填、且 start ≤ end（後端 400 為底線，這裡先攔＝少一趟往返）。
const startAfterEnd = computed(() => !!start.value && !!end.value && start.value > end.value)
const invalid = computed(() => !start.value || !end.value || startAfterEnd.value)

async function submit() {
  if (invalid.value) return // 按鈕已 disabled，這裡再守一次
  loading.value = true
  error.value = false
  try {
    const { data, error: err } = await api.GET('/api/ledger/reports/summary/range/', {
      params: { query: { start: start.value, end: end.value } },
    })
    if (err !== undefined || data === undefined) throw err ?? new Error('empty response')
    result.value = data
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

// 淨額中性色帶符號（同總覽）：方向由收支列表達，不重複著語意紅綠。
const netDisplay = computed(() => {
  const net = result.value?.net
  if (net === undefined) return ''
  return (Number(net) > 0 ? '+' : '') + formatAmount(net)
})
</script>

<template>
  <Card class="flex flex-col gap-3">
    <div class="flex flex-wrap items-end gap-2">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-ink-2">起日</span>
        <input
          v-model="start"
          type="date"
          data-test="range-start"
          class="border-hairline rounded-lg border px-2 py-1.5"
        />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-ink-2">迄日（含當日）</span>
        <input
          v-model="end"
          type="date"
          data-test="range-end"
          class="border-hairline rounded-lg border px-2 py-1.5"
        />
      </label>
      <button
        data-test="range-submit"
        class="bg-brand-fill rounded-lg px-4 py-1.5 text-sm text-white disabled:opacity-50"
        :disabled="invalid || loading"
        @click="submit"
      >
        查詢
      </button>
    </div>
    <p v-if="startAfterEnd" class="text-expense text-sm">起日不可晚於迄日</p>

    <p v-if="error" class="text-ink-2 py-4 text-center">{{ loadErrorText }}</p>
    <template v-else-if="result">
      <Row>
        <span class="text-ink-2">收入</span>
        <Amount :value="result.income" type="income" />
      </Row>
      <Row>
        <span class="text-ink-2">支出</span>
        <Amount :value="result.expense" type="expense" />
      </Row>
      <Row class="border-hairline border-t pt-2">
        <span>淨額</span>
        <span class="font-medium">{{ netDisplay }}</span>
      </Row>
    </template>
  </Card>
</template>
