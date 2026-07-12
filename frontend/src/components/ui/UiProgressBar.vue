<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ percent: number }>()

const width = computed(() => `${Math.min(Math.max(props.percent, 0), 100)}%`)
</script>

<template>
  <div class="bg-track h-2.5 overflow-hidden rounded-full">
    <div class="bg-brand-fill h-full rounded-full" :style="{ width }"></div>
  </div>
</template>
