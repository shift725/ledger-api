<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const TABS = [
  { key: 'balance', label: '餘額走勢' },
  { key: 'category', label: '分類' },
  { key: 'tags', label: '標籤' },
  { key: 'range', label: '自訂區間' },
] as const
type TabKey = (typeof TABS)[number]['key']
const KEYS = TABS.map((t) => t.key) as readonly TabKey[]

const route = useRoute()
const router = useRouter()

// URL query ＝真相：?tab= 決定現行 tab；缺省或無效值 → 第一張（餘額走勢）。
const activeTab = computed<TabKey>(() => {
  const q = route.query.tab
  return KEYS.includes(q as TabKey) ? (q as TabKey) : 'balance'
})

// 切 tab 用 replace：不堆歷史、返回鍵一次離開報表頁；?tab= 仍可定址（重整/書籤不丟）。
function selectTab(key: TabKey) {
  if (key !== activeTab.value) router.replace({ query: { tab: key } })
}
</script>

<template>
  <header class="mb-3.5">
    <h1 class="text-xl font-medium">報表</h1>
  </header>

  <nav class="border-hairline mb-3.5 flex gap-1 border-b" role="tablist">
    <button
      v-for="t in TABS"
      :key="t.key"
      role="tab"
      :aria-selected="t.key === activeTab"
      class="-mb-px border-b-2 px-3 py-2 text-sm"
      :class="
        t.key === activeTab
          ? 'border-brand-fill text-brand-text font-medium'
          : 'text-ink-2 border-transparent'
      "
      @click="selectTab(t.key)"
    >
      {{ t.label }}
    </button>
  </nav>

  <!-- 各 tab 內容陸續接入；先留佔位以立骨架。 -->
  <section :data-test="`pane-${activeTab}`" class="text-ink-2 py-6 text-center">
    {{ TABS.find((t) => t.key === activeTab)?.label }}
  </section>
</template>
