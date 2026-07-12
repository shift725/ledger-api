<script setup lang="ts">
defineProps<{ color: string }>()
</script>

<template>
  <i
    data-test="dot"
    class="inline-block h-2 w-2 shrink-0 rounded-full"
    :style="{ background: color }"
  ></i>
</template>
