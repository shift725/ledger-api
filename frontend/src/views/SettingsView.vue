<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { SETTINGS_SECTIONS } from '@/lib/settingsSections'

// 「更多」清單頁（手機鑽入；桌面 sidebar 已直達六子項）。六個子頁連結＋登出入口。
const router = useRouter()
const auth = useAuthStore()

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <header class="mb-3.5">
    <h1 class="text-xl font-medium">更多</h1>
  </header>
  <p class="text-ink-2 mb-3 text-sm">登入身分：{{ auth.user?.username }}</p>

  <nav class="bg-card rounded-card divide-hairline divide-y">
    <RouterLink
      v-for="s in SETTINGS_SECTIONS"
      :key="s.slug"
      :to="`/settings/${s.slug}`"
      class="text-ink flex items-center justify-between px-4 py-3"
    >
      <span>{{ s.label }}</span>
      <span class="text-ink-2" aria-hidden="true">›</span>
    </RouterLink>
  </nav>

  <button
    type="button"
    data-test="logout"
    class="border-frame text-ink mt-4 w-full rounded-md border px-4 py-2.5"
    @click="onLogout"
  >
    登出
  </button>
</template>
