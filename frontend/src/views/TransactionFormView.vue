<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { useReferenceStore } from '@/stores/reference'
import { toDatetimeLocal } from '@/lib/format'
import { toast } from '@/lib/toast'
import { messagesFrom } from '@/lib/errors'
import { enqueue, type TxnWrite } from '@/lib/offlineQueue'
import { loadErrorText } from '@/lib/online'
import Card from '@/components/ui/UiCard.vue'

type Transaction = components['schemas']['Transaction']

const router = useRouter()
const route = useRoute()
const reference = useReferenceStore()

// 有 :id ＝編輯（同表單預填）；否則新增。
const id = computed(() => route.params.id as string | undefined)
const isEdit = computed(() => Boolean(id.value))
const notFound = ref(false)
// 編輯內容載不到（網路錯）≠ 404：顯示可重試的失敗態，且不給空表單——
// 否則離線點編輯會看到空白欄位，一按儲存就把空值 PATCH 上去。
const loadFailed = ref(false)
const deleteDialog = ref<HTMLDialogElement | null>(null)

// 契約必填僅 account/amount/type → 主層極簡，其餘進次層收合。
const form = reactive({
  amount: '',
  type: 'expense' as 'income' | 'expense',
  account: '',
  occurredAt: toDatetimeLocal(new Date()), // 預設現在，一律明送
  category: '',
  tags: [] as string[],
  name: '',
  description: '',
})

const showMore = ref(false)
const amountError = ref('')
const accountError = ref('')
const serverError = ref('')

const AMOUNT_RE = /^\d+(\.\d{1,2})?$/
function validateAmount(): boolean {
  if (!AMOUNT_RE.test(form.amount) || Number(form.amount) <= 0) {
    amountError.value = '金額需為大於 0 的數字（至多兩位小數）'
    return false
  }
  amountError.value = ''
  return true
}

function toggleTag(id: string) {
  const i = form.tags.indexOf(id)
  if (i === -1) form.tags.push(id)
  else form.tags.splice(i, 1)
}

async function submit() {
  serverError.value = ''
  const amountOk = validateAmount()
  // 帳戶為空只可能是「使用者一個帳戶都還沒建」（有帳戶時預設會選好）→ 欄位下方引導去設定，
  // 擋在送出前，不讓空值打到後端拿一句英文的 "This field may not be null."
  accountError.value = form.account ? '' : '尚未設定帳戶，請先到「更多 → 帳戶」新增帳戶後再記帳。'
  if (!amountOk || accountError.value) return
  const payload = {
    account: form.account,
    amount: form.amount,
    type: form.type,
    occurred_at: new Date(form.occurredAt).toISOString(), // 明送 instant：離線佇列補送時時間戳仍是記帳當下
    category: form.category || null,
    tags: form.tags,
    name: form.name,
    description: form.description,
  } satisfies TxnWrite
  // 契約以同一 Transaction 型別描述 body，含 readonly 衍生欄 → 單點轉型送出。
  const body = payload as unknown as Transaction
  let result
  try {
    result = isEdit.value
      ? await api.PATCH('/api/ledger/transactions/{id}/', {
          params: { path: { id: id.value! } },
          body,
        })
      : await api.POST('/api/ledger/transactions/', { body })
  } catch {
    // fetch 直接炸＝網路不通。新增交易入離線佇列（恢復連線自動補送）；
    // 編輯不入隊——離線編輯的順序與衝突問題不在範圍，如實顯示失敗。
    if (!isEdit.value) {
      enqueue(payload)
      toast('目前離線：已存入待送佇列，恢復連線後自動補送')
      router.push('/transactions')
    } else {
      serverError.value = '網路連線失敗，請稍後再試'
    }
    return
  }
  // narrow 前先取出：契約只描述成功形狀 → error 型別為 never，
  // 對 result 整體做 truthy narrow 會讓 union collapse 成 never。
  const submitError: unknown = result.error
  if (submitError) {
    serverError.value = messagesFrom(submitError)
    return
  }
  toast('已儲存')
  router.push('/transactions')
}

async function confirmDelete() {
  deleteDialog.value?.close?.()
  let result
  try {
    result = await api.DELETE('/api/ledger/transactions/{id}/', {
      params: { path: { id: id.value! } },
    })
  } catch {
    serverError.value = '網路連線失敗，請稍後再試'
    return
  }
  const deleteError: unknown = result.error
  if (deleteError) {
    serverError.value = messagesFrom(deleteError)
    return
  }
  toast('已刪除')
  router.push('/transactions')
}

onMounted(async () => {
  await reference.ensure()
  if (isEdit.value) {
    let res
    try {
      res = await api.GET('/api/ledger/transactions/{id}/', {
        params: { path: { id: id.value! } },
      })
    } catch {
      loadFailed.value = true // 網路不通（多半離線）——不是 404，別說「找不到」
      return
    }
    const { data, error } = res
    if (error || !data) {
      notFound.value = true // 跨用戶亦回 404（後端藏存在性）→ 一律「找不到」，不提權限
      return
    }
    form.amount = data.amount
    form.type = data.type
    form.account = data.account
    form.occurredAt = toDatetimeLocal(new Date(data.occurred_at ?? Date.now()))
    form.category = data.category ?? ''
    form.tags = [...(data.tags ?? [])]
    form.name = data.name ?? ''
    form.description = data.description ?? ''
    // 次層有值就展開，讓使用者一眼看到既有內容
    if (form.category || form.tags.length || form.name || form.description) showMore.value = true
  } else {
    const def = reference.accounts.find((a) => a.is_default) ?? reference.accounts[0]
    if (def) form.account = def.id
  }
})
</script>

<template>
  <header class="mb-3.5 flex items-baseline justify-between">
    <h1 class="text-xl font-medium">{{ isEdit ? '編輯交易' : '記一筆' }}</h1>
    <RouterLink v-if="!isEdit" to="/transactions/transfer" class="text-brand-text text-sm">
      轉帳
    </RouterLink>
  </header>

  <p v-if="notFound" class="text-ink-2 py-10 text-center">找不到這筆交易</p>

  <p v-else-if="loadFailed" class="text-ink-2 py-10 text-center">{{ loadErrorText }}</p>

  <form v-else class="flex flex-col gap-2.5" @submit.prevent="submit">
    <Card class="flex flex-col gap-3">
      <!-- 收支切換 -->
      <div class="border-hairline flex overflow-hidden rounded-lg border">
        <button
          v-for="opt in [
            { v: 'expense', label: '支出' },
            { v: 'income', label: '收入' },
          ]"
          :key="opt.v"
          type="button"
          class="flex-1 py-2 text-sm"
          :class="form.type === opt.v ? 'bg-brand-fill text-white' : 'text-ink-2'"
          @click="form.type = opt.v as 'income' | 'expense'"
        >
          {{ opt.label }}
        </button>
      </div>

      <!-- 金額 -->
      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">金額</span>
        <input
          v-model="form.amount"
          data-test="form-amount"
          inputmode="decimal"
          placeholder="0.00"
          class="border-hairline rounded-lg border px-3 py-2 text-lg"
        />
        <span v-if="amountError" class="text-expense text-sm">{{ amountError }}</span>
      </label>

      <!-- 帳戶 -->
      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">帳戶</span>
        <select
          v-model="form.account"
          data-test="form-account"
          class="border-hairline rounded-lg border px-3 py-2"
        >
          <option v-for="a in reference.accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select>
        <span v-if="accountError" data-test="form-account-error" class="text-expense text-sm">{{
          accountError
        }}</span>
      </label>

      <!-- 日期時間 -->
      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">日期時間</span>
        <input
          v-model="form.occurredAt"
          type="datetime-local"
          class="border-hairline rounded-lg border px-3 py-2"
        />
      </label>
    </Card>

    <!-- 次層收合 -->
    <button
      type="button"
      data-test="toggle-more"
      class="text-brand-text text-sm font-medium"
      @click="showMore = !showMore"
    >
      {{ showMore ? '收合' : '更多欄位' }}
    </button>

    <Card v-if="showMore" class="flex flex-col gap-3">
      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">分類</span>
        <select
          v-model="form.category"
          data-test="form-category"
          class="border-hairline rounded-lg border px-3 py-2"
        >
          <option value="">未分類</option>
          <option v-for="c in reference.categories" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </label>

      <div v-if="reference.tags.length" class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">標籤</span>
        <div class="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          <label v-for="t in reference.tags" :key="t.id" class="flex items-center gap-1">
            <input
              type="checkbox"
              :checked="form.tags.includes(t.id)"
              @change="toggleTag(t.id)"
            />{{ t.name }}
          </label>
        </div>
      </div>

      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">名稱</span>
        <input
          v-model="form.name"
          data-test="form-name"
          maxlength="200"
          class="border-hairline rounded-lg border px-3 py-2"
        />
      </label>

      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">說明</span>
        <textarea
          v-model="form.description"
          rows="2"
          class="border-hairline rounded-lg border px-3 py-2"
        ></textarea>
      </label>
    </Card>

    <p v-if="serverError" data-test="form-error" class="text-expense text-sm">{{ serverError }}</p>

    <button
      type="submit"
      data-test="form-submit"
      class="bg-brand-fill rounded-lg py-2.5 font-medium text-white"
    >
      儲存
    </button>

    <!-- 刪除（僅編輯）：原生 <dialog> 二次確認 -->
    <button
      v-if="isEdit"
      type="button"
      data-test="open-delete"
      class="text-expense py-1 text-sm"
      @click="deleteDialog?.showModal?.()"
    >
      刪除這筆交易
    </button>
  </form>

  <dialog ref="deleteDialog" class="rounded-card m-auto p-5 backdrop:bg-black/30">
    <p class="mb-4">確定刪除這筆交易？此動作無法復原。</p>
    <div class="flex justify-end gap-2">
      <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="deleteDialog?.close?.()">
        取消
      </button>
      <button
        type="button"
        data-test="confirm-delete"
        class="bg-expense dark:text-bg rounded-lg px-3 py-1.5 text-sm text-white"
        @click="confirmDelete"
      >
        刪除
      </button>
    </div>
  </dialog>
</template>
