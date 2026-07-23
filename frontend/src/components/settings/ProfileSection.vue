<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { useAuthStore } from '@/stores/auth'
import { messagesFrom } from '@/lib/errors'
import { toast } from '@/lib/toast'
import { useSubmitting } from '@/lib/useSubmitting'

type User = components['schemas']['User']

const auth = useAuthStore()
const ROLE_LABELS: Record<string, string> = { admin: '管理員', staff: '員工', member: '會員' }

const loaded = ref(false)
const notFound = ref(false)
const formError = ref('')
// role/created_at 顯示不可編（role 由 staff 管理、created_at 系統時戳）。
const display = reactive({ role: '', createdAt: '' })
const form = reactive({ username: '', email: '', phone: '' })

onMounted(async () => {
  const id = auth.user?.id
  if (!id) {
    notFound.value = true
    return
  }
  const { data, error } = await api.GET('/api/auth/users/{id}/', { params: { path: { id } } })
  if (error || !data) {
    notFound.value = true
    return
  }
  fill(data)
  loaded.value = true
})

function fill(u: User) {
  form.username = u.username
  form.email = u.email
  form.phone = u.phone ?? ''
  display.role = ROLE_LABELS[u.role ?? 'member'] ?? u.role ?? ''
  display.createdAt = (u.created_at ?? '').slice(0, 10)
}

async function doSubmit() {
  formError.value = ''
  const id = auth.user?.id
  if (!id) return
  const { data, error } = await api.PATCH('/api/auth/users/{id}/', {
    params: { path: { id } },
    body: { username: form.username, email: form.email, phone: form.phone },
  })
  if (error || !data) {
    formError.value = messagesFrom(error) // 帳號/email 重複等 400 逐欄如實顯示
    return
  }
  fill(data)
  // 同步 store 追蹤的欄位，讓殼顯示的使用者名稱即時更新。
  auth.updateUser({ username: data.username, email: data.email })
  toast('已儲存')
}

// 送出期間鎖住按鈕：這支是冪等的 PATCH，鎖住為的是按壓回饋與全站行為一致。
const { submitting, run: submit } = useSubmitting(doSubmit)
</script>

<template>
  <p v-if="notFound" class="text-ink-2 py-10 text-center">找不到個人資料</p>

  <form v-else-if="loaded" class="flex flex-col gap-3" @submit.prevent="submit">
    <label class="flex flex-col gap-1">
      <span class="text-ink-2 text-sm">帳號</span>
      <input
        v-model="form.username"
        data-test="profile-username"
        class="border-hairline rounded-lg border px-3 py-2"
      />
    </label>

    <label class="flex flex-col gap-1">
      <span class="text-ink-2 text-sm">Email</span>
      <input
        v-model="form.email"
        data-test="profile-email"
        type="email"
        class="border-hairline rounded-lg border px-3 py-2"
      />
    </label>

    <label class="flex flex-col gap-1">
      <span class="text-ink-2 text-sm">電話</span>
      <input
        v-model="form.phone"
        data-test="profile-phone"
        class="border-hairline rounded-lg border px-3 py-2"
      />
    </label>

    <dl class="text-ink-2 flex gap-6 text-sm">
      <div class="flex gap-1">
        <dt>身分</dt>
        <dd data-test="profile-role" class="text-ink">{{ display.role }}</dd>
      </div>
      <div class="flex gap-1">
        <dt>註冊於</dt>
        <dd class="text-ink">{{ display.createdAt }}</dd>
      </div>
    </dl>

    <p v-if="formError" data-test="profile-error" class="text-expense text-sm">{{ formError }}</p>

    <button
      type="submit"
      data-test="profile-submit"
      :disabled="submitting"
      class="bg-brand-fill self-start rounded-lg px-4 py-2 text-sm text-white disabled:opacity-60"
    >
      儲存
    </button>
  </form>
</template>
