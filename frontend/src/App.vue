<script setup lang="ts">
import { watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AppShell from '@/components/AppShell.vue'
import { isOnline } from '@/lib/online'
import { replay, syncCount } from '@/lib/offlineQueue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()

// 離線佇列重放的三個時機收斂成一個 watch：App 啟動（immediate）、恢復連線、
// 登入（登入前佇列 key 組不出來）。replay 自身 single-flight＋空隊快速返回；
// 離線啟動送不出去，但 banner 的待送筆數仍要從 localStorage 對齊。
watch(
  [isOnline, () => auth.user],
  ([online, user]) => {
    if (!user) return
    syncCount()
    if (online) void replay()
  },
  { immediate: true },
)
</script>

<template>
  <!-- 殼只給受保護路由；認證頁維持極簡置中版面 -->
  <AppShell v-if="route.meta.requiresAuth">
    <RouterView />
  </AppShell>
  <div v-else class="min-h-screen">
    <header class="mx-auto max-w-md px-4 py-3">
      <h1 class="text-brand-text text-xl font-medium">晴空記帳</h1>
    </header>
    <main class="mx-auto max-w-md px-4">
      <RouterView />
    </main>
  </div>
</template>
