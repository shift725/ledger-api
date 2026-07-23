<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/auth'
import { useSubmitting } from '@/lib/useSubmitting'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const error = ref('')

async function doSubmit() {
  error.value = ''
  try {
    await auth.login(email.value, password.value)
  } catch (e) {
    error.value = e instanceof ApiError ? '登入失敗，請檢查帳號與密碼' : '發生錯誤，請稍後再試'
    return
  }
  const redirect = route.query.redirect
  // 必須 await：route 是 lazy import（() => import），不等它完成的話，送出鍵會在
  // chunk 還在下載時就解鎖，而此刻表單仍掛著、欄位仍有值 → 慢網路下還能再送出一次。
  await router.push(typeof redirect === 'string' ? redirect : '/')
}

// 送出期間鎖住按鈕（機制與接法見 lib/useSubmitting.ts）。
const { submitting, run: onSubmit } = useSubmitting(doSubmit)
</script>

<template>
  <form class="mx-auto mt-8 flex max-w-sm flex-col gap-4" @submit.prevent="onSubmit">
    <h2 class="text-brand-text text-lg font-medium">登入</h2>

    <label class="flex flex-col gap-1 text-sm">
      Email
      <input
        v-model="email"
        type="email"
        required
        autocomplete="email"
        class="rounded-md border border-frame px-3 py-2"
      />
    </label>

    <label class="flex flex-col gap-1 text-sm">
      密碼
      <input
        v-model="password"
        type="password"
        required
        autocomplete="current-password"
        class="rounded-md border border-frame px-3 py-2"
      />
    </label>

    <p v-if="error" role="alert" class="text-expense text-sm">{{ error }}</p>

    <button
      type="submit"
      :disabled="submitting"
      class="bg-brand-fill rounded-md py-2 text-white disabled:opacity-60"
    >
      登入
    </button>

    <RouterLink to="/register" class="text-brand-text text-center text-sm">
      還沒有帳號？註冊
    </RouterLink>
  </form>
</template>
