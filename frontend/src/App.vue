<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router'
import AppShell from '@/components/AppShell.vue'

const route = useRoute()
</script>

<template>
  <!-- 殼只給受保護路由；認證頁維持極簡置中版面 -->
  <AppShell v-if="route.meta.requiresAuth">
    <RouterView />
  </AppShell>
  <div v-else class="min-h-screen">
    <header class="mx-auto max-w-md px-4 py-3">
      <h1 class="text-brand-text text-xl font-medium">分類帳</h1>
    </header>
    <main class="mx-auto max-w-md px-4">
      <RouterView />
    </main>
  </div>
</template>
