<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/auth'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const email = ref('')
const password = ref('')
const passwordConfirm = ref('')
const phone = ref('')
const error = ref('')
const submitting = ref(false)

// Surface the first backend message from a DRF 400 ({field: [msg]}) or the 409
// ({error: msg}) so validation failures are actionable, not a generic blurb.
function firstError(body: unknown): string {
  if (body && typeof body === 'object') {
    for (const v of Object.values(body as Record<string, unknown>)) {
      if (Array.isArray(v) && typeof v[0] === 'string') return v[0]
      if (typeof v === 'string') return v
    }
  }
  return '註冊失敗，請檢查輸入'
}

async function onSubmit() {
  error.value = ''
  submitting.value = true
  try {
    await auth.register({
      username: username.value,
      email: email.value,
      password: password.value,
      password_confirm: passwordConfirm.value,
      phone: phone.value || undefined,
    })
    router.push('/')
  } catch (e) {
    error.value = e instanceof ApiError ? firstError(e.body) : '發生錯誤，請稍後再試'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="mx-auto mt-8 flex max-w-sm flex-col gap-4" @submit.prevent="onSubmit">
    <h2 class="text-brand-text text-lg font-medium">註冊</h2>

    <label class="flex flex-col gap-1 text-sm">
      使用者名稱
      <input
        v-model="username"
        required
        autocomplete="username"
        class="rounded-md border border-frame px-3 py-2"
      />
    </label>

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
        autocomplete="new-password"
        class="rounded-md border border-frame px-3 py-2"
      />
    </label>

    <label class="flex flex-col gap-1 text-sm">
      確認密碼
      <input
        v-model="passwordConfirm"
        type="password"
        required
        autocomplete="new-password"
        class="rounded-md border border-frame px-3 py-2"
      />
    </label>

    <label class="flex flex-col gap-1 text-sm">
      電話（選填）
      <input
        v-model="phone"
        type="tel"
        autocomplete="tel"
        class="rounded-md border border-frame px-3 py-2"
      />
    </label>

    <p v-if="error" role="alert" class="text-expense text-sm">{{ error }}</p>

    <button
      type="submit"
      :disabled="submitting"
      class="bg-brand-fill rounded-md py-2 text-white disabled:opacity-60"
    >
      註冊
    </button>

    <RouterLink to="/login" class="text-brand-text text-center text-sm">已有帳號？登入</RouterLink>
  </form>
</template>
