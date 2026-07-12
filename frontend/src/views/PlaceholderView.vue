<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="bg-card rounded-card px-4 py-6 text-center">
    <p class="text-ink font-medium">開發中</p>
    <p class="text-ink-2 mt-1 text-sm">{{ route.path }} 屬後續開發範圍</p>
  </section>
</template>
