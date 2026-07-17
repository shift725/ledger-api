<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { fetchAll, useReferenceStore } from '@/stores/reference'
import { messagesFrom } from '@/lib/errors'
import { toast } from '@/lib/toast'
import UiAmount from '@/components/ui/UiAmount.vue'
import UiBadge from '@/components/ui/UiBadge.vue'

type RecurringRule = components['schemas']['RecurringRule']
// 契約無獨立寫入型別 → 送出前剝唯讀衍生欄，單點轉型送出。
type RuleWrite = Omit<
  RecurringRule,
  'id' | 'next_run_date' | 'account_name' | 'category_name' | 'is_active'
>

// 定期定額不在 reference store（非表單共用清單）→ 自抓自管；帳戶/分類下拉才吃 reference。
const reference = useReferenceStore()
const rules = ref<RecurringRule[]>([])

const dialog = ref<HTMLDialogElement | null>(null)
const deleteDialog = ref<HTMLDialogElement | null>(null)
const editingId = ref<string | null>(null)
const pendingDeleteId = ref<string | null>(null)
const formError = ref('')
const form = reactive<RuleWrite>({
  account: '',
  category: null,
  amount: '',
  type: 'expense',
  name: '',
  description: '',
  day_of_month: new Date().getDate(),
})

async function load() {
  rules.value = await fetchAll<RecurringRule>((page) =>
    api.GET('/api/ledger/recurring-rules/', { params: { query: { page } } }),
  )
}

onMounted(async () => {
  await reference.ensure()
  await load()
})

function openCreate() {
  editingId.value = null
  const def = reference.accounts.find((a) => a.is_default) ?? reference.accounts[0]
  Object.assign(form, {
    account: def?.id ?? '',
    category: null,
    amount: '',
    type: 'expense',
    name: '',
    description: '',
    day_of_month: new Date().getDate(),
  })
  formError.value = ''
  dialog.value?.showModal()
}

function openEdit(rule: RecurringRule) {
  editingId.value = rule.id
  Object.assign(form, {
    account: rule.account,
    category: rule.category ?? null,
    amount: rule.amount,
    type: rule.type,
    name: rule.name ?? '',
    description: rule.description ?? '',
    day_of_month: rule.day_of_month,
  })
  formError.value = ''
  dialog.value?.showModal()
}

const AMOUNT_RE = /^\d+(\.\d{1,2})?$/
function validate(): boolean {
  if (!form.account) {
    formError.value = '請選擇帳戶'
    return false
  }
  if (!AMOUNT_RE.test(form.amount) || Number(form.amount) <= 0) {
    formError.value = '金額需為大於 0 的數字（至多兩位小數）'
    return false
  }
  if (!Number.isInteger(form.day_of_month) || form.day_of_month < 1 || form.day_of_month > 31) {
    formError.value = '扣款日需為 1–31'
    return false
  }
  return true
}

async function submit() {
  formError.value = ''
  if (!validate()) return
  const body = { ...form, category: form.category || null } as unknown as RecurringRule
  const { error } = editingId.value
    ? await api.PATCH('/api/ledger/recurring-rules/{id}/', {
        params: { path: { id: editingId.value } },
        body,
      })
    : await api.POST('/api/ledger/recurring-rules/', { body })
  if (error) {
    formError.value = messagesFrom(error)
    return
  }
  dialog.value?.close()
  await load()
  toast('已儲存')
}

async function toggleActive(rule: RecurringRule) {
  // 停用≠停機：暫停期間不補記，重新啟用時後端從今日重算 next_run_date。
  const { error } = await api.PATCH('/api/ledger/recurring-rules/{id}/', {
    params: { path: { id: rule.id } },
    body: { is_active: !rule.is_active },
  })
  if (error) {
    toast(messagesFrom(error))
    return
  }
  await load()
}

function askDelete(id: string) {
  pendingDeleteId.value = id
  deleteDialog.value?.showModal()
}

async function confirmDelete() {
  deleteDialog.value?.close()
  const id = pendingDeleteId.value
  if (!id) return
  const { error } = await api.DELETE('/api/ledger/recurring-rules/{id}/', {
    params: { path: { id } },
  })
  if (error) {
    toast(messagesFrom(error))
    return
  }
  await load()
  toast('已刪除')
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <button
      type="button"
      data-test="rule-new"
      class="bg-brand-fill self-start rounded-lg px-3 py-1.5 text-sm text-white"
      @click="openCreate"
    >
      新增定期定額
    </button>

    <p class="text-ink-2 text-xs">停用期間不補記，重新啟用後從今日重算下次扣款日。</p>

    <p v-if="rules.length === 0" class="text-ink-2 py-6 text-center text-sm">尚無定期定額</p>

    <ul v-else class="flex flex-col gap-2">
      <li
        v-for="rule in rules"
        :key="rule.id"
        data-test="rule-row"
        class="bg-card rounded-card flex items-center justify-between gap-2 px-4 py-3"
      >
        <div class="min-w-0">
          <p class="text-ink flex items-center gap-2">
            <span class="truncate">{{
              rule.name || (rule.type === 'income' ? '收入' : '支出')
            }}</span>
            <UiBadge v-if="!rule.is_active">已停用</UiBadge>
          </p>
          <p class="text-ink-2 text-xs">
            每月 {{ rule.day_of_month }} 號 · 下次 {{ rule.next_run_date }}
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-3 text-xs">
          <UiAmount :value="rule.amount" :type="rule.type" signed class="text-sm" />
          <button
            type="button"
            data-test="rule-active-toggle"
            class="text-brand-text"
            @click="toggleActive(rule)"
          >
            {{ rule.is_active ? '停用' : '啟用' }}
          </button>
          <button type="button" data-test="rule-edit" class="text-ink-2" @click="openEdit(rule)">
            編輯
          </button>
          <button
            type="button"
            data-test="rule-delete"
            class="text-expense"
            @click="askDelete(rule.id)"
          >
            刪除
          </button>
        </div>
      </li>
    </ul>

    <!-- 新增／編輯共用 dialog -->
    <dialog ref="dialog" class="rounded-card m-auto w-80 max-w-[90vw] p-5 backdrop:bg-black/30">
      <form class="flex flex-col gap-3" @submit.prevent="submit">
        <h2 class="font-medium">{{ editingId ? '編輯定期定額' : '新增定期定額' }}</h2>

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

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">金額</span>
          <input
            v-model="form.amount"
            data-test="rule-amount"
            inputmode="decimal"
            placeholder="0.00"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">帳戶</span>
          <select
            v-model="form.account"
            data-test="rule-account"
            class="border-hairline rounded-lg border px-3 py-2"
          >
            <option v-for="a in reference.accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">每月扣款日</span>
          <input
            v-model.number="form.day_of_month"
            data-test="rule-day"
            type="number"
            min="1"
            max="31"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">分類（選填）</span>
          <select
            v-model="form.category"
            data-test="rule-category"
            class="border-hairline rounded-lg border px-3 py-2"
          >
            <option :value="null">未分類</option>
            <option v-for="c in reference.categories" :key="c.id" :value="c.id">
              {{ c.name }}
            </option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">名稱（選填）</span>
          <input
            v-model="form.name"
            data-test="rule-name"
            maxlength="200"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>

        <p v-if="formError" data-test="rule-error" class="text-expense text-sm">{{ formError }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="dialog?.close()">
            取消
          </button>
          <button
            type="submit"
            data-test="rule-submit"
            class="bg-brand-fill rounded-lg px-3 py-1.5 text-sm text-white"
          >
            儲存
          </button>
        </div>
      </form>
    </dialog>

    <!-- 刪除確認 -->
    <dialog ref="deleteDialog" class="rounded-card m-auto p-5 backdrop:bg-black/30">
      <p class="mb-4">確定刪除此定期定額？</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="deleteDialog?.close()">
          取消
        </button>
        <button
          type="button"
          data-test="rule-confirm-delete"
          class="bg-expense dark:text-bg rounded-lg px-3 py-1.5 text-sm text-white"
          @click="confirmDelete"
        >
          刪除
        </button>
      </div>
    </dialog>
  </div>
</template>
