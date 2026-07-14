<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { SETTINGS_SECTIONS } from '@/lib/settingsSections'
import AccountsSection from '@/components/settings/AccountsSection.vue'

// /settings/:section 的派發殼：驗 slug、掛標題、依 slug 掛對應區塊元件。
// 尚未實作的 slug 落佔位；未知 slug → 找不到此頁。
const sectionComponents: Record<string, Component> = {
  accounts: AccountsSection,
}
const route = useRoute()
const section = computed(() => SETTINGS_SECTIONS.find((s) => s.slug === route.params.section))
const body = computed(() => (section.value ? sectionComponents[section.value.slug] : undefined))
</script>

<template>
  <template v-if="section">
    <header class="mb-3.5">
      <h1 class="text-xl font-medium">{{ section.label }}</h1>
    </header>
    <component :is="body" v-if="body" />
    <section
      v-else
      :data-test="`section-${section.slug}`"
      class="bg-card rounded-card px-4 py-6 text-center"
    >
      <p class="text-ink-2 text-sm">此區塊開發中</p>
    </section>
  </template>
  <p v-else data-test="section-not-found" class="text-ink-2 py-10 text-center">找不到此頁</p>
</template>
