<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

async function onLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <!-- Placeholder home; the real dashboard replaces this later. -->
  <section class="mx-auto mt-8 flex max-w-md flex-col gap-4">
    <p class="text-ink">登入身分：{{ auth.user?.username }}</p>
    <button
      type="button"
      class="border-frame text-ink self-start rounded-md border px-4 py-2"
      @click="onLogout"
    >
      登出
    </button>
  </section>
</template>
