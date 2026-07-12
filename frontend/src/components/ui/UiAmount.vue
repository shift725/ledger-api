<script setup lang="ts">
import { computed } from 'vue'
import { formatAmount } from '@/lib/format'

// 語意紅綠只上有方向性的非零金額；零值無方向，muted 呈現。
const props = defineProps<{
  value: string
  type?: 'income' | 'expense'
  signed?: boolean
}>()

const isZero = computed(() => Number(props.value) === 0)

const colorClass = computed(() => {
  if (!props.type) return null
  if (isZero.value) return 'text-ink-2'
  return props.type === 'income' ? 'text-income font-medium' : 'text-expense font-medium'
})

const display = computed(() => {
  const sign = props.signed && !isZero.value ? (props.type === 'income' ? '+' : '-') : ''
  return sign + formatAmount(props.value)
})
</script>

<template>
  <span :class="colorClass">{{ display }}</span>
</template>
