<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BalanceHistoryTab from '@/components/reports/BalanceHistoryTab.vue'
import CategoryTab from '@/components/reports/CategoryTab.vue'
import TagsTab from '@/components/reports/TagsTab.vue'
import RangeTab from '@/components/reports/RangeTab.vue'

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

  <!-- KeepAlive 保活已抓過的 tab：切走 deactivate、切回 activate 不重掛＝不重抓
       （尤其 balance-history 貴）；range 保活則保住已填的起迄日。 -->
  <KeepAlive>
    <BalanceHistoryTab v-if="activeTab === 'balance'" />
    <CategoryTab v-else-if="activeTab === 'category'" />
    <TagsTab v-else-if="activeTab === 'tags'" />
    <RangeTab v-else-if="activeTab === 'range'" />
  </KeepAlive>
</template>
