<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { SETTINGS_SECTIONS } from '@/lib/settingsSections'

// /settings/:section 的派發殼：驗 slug、掛標題；各資源的真內容之後在對應區塊
// 元件實作，此處只認得合法的六個 slug。未知 slug → 找不到此頁。
const route = useRoute()
const section = computed(() => SETTINGS_SECTIONS.find((s) => s.slug === route.params.section))
</script>

<template>
  <template v-if="section">
    <header class="mb-3.5">
      <h1 class="text-xl font-medium">{{ section.label }}</h1>
    </header>
    <section
      :data-test="`section-${section.slug}`"
      class="bg-card rounded-card px-4 py-6 text-center"
    >
      <p class="text-ink-2 text-sm">此區塊開發中</p>
    </section>
  </template>
  <p v-else data-test="section-not-found" class="text-ink-2 py-10 text-center">找不到此頁</p>
</template>
