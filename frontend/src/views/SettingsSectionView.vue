<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { SETTINGS_SECTIONS } from '@/lib/settingsSections'
import AccountsSection from '@/components/settings/AccountsSection.vue'
import SimpleResourceSection from '@/components/settings/SimpleResourceSection.vue'
import RulesSection from '@/components/settings/RulesSection.vue'
import GoalsSection from '@/components/settings/GoalsSection.vue'

// /settings/:section 的派發殼：驗 slug、掛標題、依 slug 掛對應區塊元件（可帶 props）。
// 尚未實作的 slug 落佔位；未知 slug → 找不到此頁。分類/標籤同形共用泛用元件。
interface SectionEntry {
  comp: Component
  props?: Record<string, unknown>
}
const sectionComponents: Record<string, SectionEntry> = {
  accounts: { comp: AccountsSection },
  categories: { comp: SimpleResourceSection, props: { resource: 'categories' } },
  tags: { comp: SimpleResourceSection, props: { resource: 'tags' } },
  rules: { comp: RulesSection },
  goals: { comp: GoalsSection },
}
const route = useRoute()
const section = computed(() => SETTINGS_SECTIONS.find((s) => s.slug === route.params.section))
const entry = computed(() => (section.value ? sectionComponents[section.value.slug] : undefined))
</script>

<template>
  <template v-if="section">
    <header class="mb-3.5">
      <h1 class="text-xl font-medium">{{ section.label }}</h1>
    </header>
    <component :is="entry.comp" v-bind="entry.props" v-if="entry" />
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
