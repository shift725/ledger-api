<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/UiCard.vue'

// 「更多」清單頁的最小版：先保住登出入口（登出收在「更多」），
// 六子項管理 UI 屬後續開發，在本檔原地長大。
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
  <Card>
    <p class="text-ink">登入身分：{{ auth.user?.username }}</p>
    <p class="text-ink-2 mt-1 text-sm">帳戶、分類等管理功能屬後續開發範圍</p>
    <button
      type="button"
      class="border-frame text-ink mt-3 rounded-md border px-4 py-2"
      @click="onLogout"
    >
      登出
    </button>
  </Card>
</template>
