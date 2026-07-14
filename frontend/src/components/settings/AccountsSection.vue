<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { useReferenceStore } from '@/stores/reference'
import { accountTypeLabel } from '@/lib/format'
import { messagesFrom } from '@/lib/errors'
import { toast } from '@/lib/toast'
import UiAmount from '@/components/ui/UiAmount.vue'
import UiBadge from '@/components/ui/UiBadge.vue'

type Account = components['schemas']['Account']
type AccountType = components['schemas']['AccountTypeEnum']
// 契約無獨立寫入型別（Account 含唯讀 id/balance）→ 送出前剝唯讀衍生欄，單點轉型送出。
type AccountWrite = Omit<Account, 'id' | 'balance'>

// 列表直讀 reference store（帳戶清單的單一來源，交易表單下拉同用）；寫入後 refresh 重抓。
const reference = useReferenceStore()
const ACCOUNT_TYPES: AccountType[] = ['cash', 'bank', 'credit_card', 'e_wallet']

const dialog = ref<HTMLDialogElement | null>(null)
const deleteDialog = ref<HTMLDialogElement | null>(null)
const editingId = ref<string | null>(null) // null＝新增，否則＝編輯該 id
const pendingDeleteId = ref<string | null>(null)
const formError = ref('')
const form = reactive<AccountWrite>({ name: '', type: 'cash', is_default: false })

onMounted(() => reference.ensure())

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', type: 'cash', is_default: false })
  formError.value = ''
  dialog.value?.showModal()
}

function openEdit(acc: Account) {
  editingId.value = acc.id
  Object.assign(form, { name: acc.name, type: acc.type, is_default: acc.is_default ?? false })
  formError.value = ''
  dialog.value?.showModal()
}

async function submit() {
  formError.value = ''
  const body = { ...form } as unknown as Account
  const { error } = editingId.value
    ? await api.PATCH('/api/ledger/accounts/{id}/', {
        params: { path: { id: editingId.value } },
        body,
      })
    : await api.POST('/api/ledger/accounts/', { body })
  if (error) {
    formError.value = messagesFrom(error) // 重名 400 逐欄如實顯示
    return
  }
  dialog.value?.close()
  await reference.refresh()
  toast('已儲存')
}

async function setDefault(acc: Account) {
  if (acc.is_default) return
  // 後端單選語意（atomic 降級其他）；前端只送本筆，重抓後恰一預設。
  const { error } = await api.PATCH('/api/ledger/accounts/{id}/', {
    params: { path: { id: acc.id } },
    body: { is_default: true },
  })
  if (error) {
    toast(messagesFrom(error))
    return
  }
  await reference.refresh()
}

function askDelete(id: string) {
  pendingDeleteId.value = id
  deleteDialog.value?.showModal()
}

async function confirmDelete() {
  deleteDialog.value?.close()
  const id = pendingDeleteId.value
  if (!id) return
  const { error } = await api.DELETE('/api/ledger/accounts/{id}/', { params: { path: { id } } })
  if (error) {
    toast(messagesFrom(error)) // 409：此帳戶尚有交易 → 後端 detail 直接上屏
    return
  }
  await reference.refresh()
  toast('已刪除')
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <button
      type="button"
      data-test="account-new"
      class="bg-brand-fill self-start rounded-lg px-3 py-1.5 text-sm text-white"
      @click="openCreate"
    >
      新增帳戶
    </button>

    <p
      v-if="reference.loaded && reference.accounts.length === 0"
      class="text-ink-2 py-6 text-center text-sm"
    >
      尚無帳戶
    </p>

    <ul v-else class="flex flex-col gap-2">
      <li
        v-for="acc in reference.accounts"
        :key="acc.id"
        data-test="account-row"
        class="bg-card rounded-card flex items-center justify-between gap-2 px-4 py-3"
      >
        <div class="min-w-0">
          <p class="text-ink flex items-center gap-2">
            <span class="truncate">{{ acc.name }}</span>
            <UiBadge v-if="acc.is_default" data-test="account-default-badge">預設</UiBadge>
          </p>
          <p class="text-ink-2 text-xs">{{ accountTypeLabel(acc.type) }}</p>
        </div>
        <div class="flex shrink-0 items-center gap-3 text-xs">
          <UiAmount :value="acc.balance" class="text-ink text-sm" />
          <button
            v-if="!acc.is_default"
            type="button"
            data-test="account-set-default"
            class="text-brand-text"
            @click="setDefault(acc)"
          >
            設為預設
          </button>
          <button type="button" data-test="account-edit" class="text-ink-2" @click="openEdit(acc)">
            編輯
          </button>
          <button
            type="button"
            data-test="account-delete"
            class="text-expense"
            @click="askDelete(acc.id)"
          >
            刪除
          </button>
        </div>
      </li>
    </ul>

    <!-- 新增／編輯共用 dialog -->
    <dialog ref="dialog" class="rounded-card m-auto w-80 max-w-[90vw] p-5 backdrop:bg-black/30">
      <form class="flex flex-col gap-3" @submit.prevent="submit">
        <h2 class="font-medium">{{ editingId ? '編輯帳戶' : '新增帳戶' }}</h2>
        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">名稱</span>
          <input
            v-model="form.name"
            data-test="account-name"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">類型</span>
          <select
            v-model="form.type"
            data-test="account-type"
            class="border-hairline rounded-lg border px-3 py-2"
          >
            <option v-for="t in ACCOUNT_TYPES" :key="t" :value="t">
              {{ accountTypeLabel(t) }}
            </option>
          </select>
        </label>
        <label class="flex items-center gap-2">
          <input v-model="form.is_default" type="checkbox" data-test="account-default" />
          <span class="text-ink-2 text-sm">設為預設帳戶</span>
        </label>
        <p v-if="formError" data-test="account-error" class="text-expense text-sm">
          {{ formError }}
        </p>
        <div class="flex justify-end gap-2">
          <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="dialog?.close()">
            取消
          </button>
          <button
            type="submit"
            data-test="account-submit"
            class="bg-brand-fill rounded-lg px-3 py-1.5 text-sm text-white"
          >
            儲存
          </button>
        </div>
      </form>
    </dialog>

    <!-- 刪除確認 -->
    <dialog ref="deleteDialog" class="rounded-card m-auto p-5 backdrop:bg-black/30">
      <p class="mb-4">確定刪除此帳戶？</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="deleteDialog?.close()">
          取消
        </button>
        <button
          type="button"
          data-test="account-confirm-delete"
          class="bg-expense rounded-lg px-3 py-1.5 text-sm text-white"
          @click="confirmDelete"
        >
          刪除
        </button>
      </div>
    </dialog>
  </div>
</template>
