<script setup lang="ts">
import type { Flow } from '@/lib/reportCharts'

// 年月選擇＋收支切換，分類/標籤兩 tab 共用。契約參數是 year+month 整數 → 直接兩顆
// select（不用 input[type=month]：桌面 Safari 不支援、還得 fallback＝兩套 code path）。
const year = defineModel<number>('year', { required: true })
const month = defineModel<number>('month', { required: true })
const flow = defineModel<Flow>('flow', { required: true })

const now = new Date()
// 今年往前 5 年夠用（記帳資料不會太久遠；需要再擴）。
const years = Array.from({ length: 5 }, (_, i) => now.getFullYear() - i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
</script>

<template>
  <div class="mb-3 flex items-center gap-2">
    <select
      v-model.number="year"
      data-test="year-select"
      class="border-hairline rounded-lg border px-2 py-1.5 text-sm"
    >
      <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
    </select>
    <select
      v-model.number="month"
      data-test="month-select"
      class="border-hairline rounded-lg border px-2 py-1.5 text-sm"
    >
      <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
    </select>
    <div class="border-hairline ml-auto flex overflow-hidden rounded-lg border text-sm">
      <button
        v-for="f in ['expense', 'income'] as const"
        :key="f"
        class="px-3 py-1.5"
        :class="flow === f ? 'bg-brand-tint text-brand-text font-medium' : 'text-ink-2'"
        @click="flow = f"
      >
        {{ f === 'expense' ? '支出' : '收入' }}
      </button>
    </div>
  </div>
</template>
