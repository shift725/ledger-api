<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { fetchAll } from '@/stores/reference'
import { messagesFrom } from '@/lib/errors'
import { toast } from '@/lib/toast'
import UiAmount from '@/components/ui/UiAmount.vue'

type SavingsGoal = components['schemas']['SavingsGoal']
type PeriodType = components['schemas']['PeriodTypeEnum']
type GoalWrite = Omit<SavingsGoal, 'id'>

const goals = ref<SavingsGoal[]>([])

const dialog = ref<HTMLDialogElement | null>(null)
const deleteDialog = ref<HTMLDialogElement | null>(null)
const editingId = ref<string | null>(null)
const pendingDeleteId = ref<string | null>(null)
const formError = ref('')
const now = new Date()
const form = reactive({
  period_type: 'monthly' as PeriodType,
  year: now.getFullYear(),
  month: now.getMonth() + 1,
  amount: '',
})

async function load() {
  goals.value = await fetchAll<SavingsGoal>((page) =>
    api.GET('/api/ledger/savings-goals/', { params: { query: { page } } }),
  )
}

onMounted(load)

function periodLabel(goal: SavingsGoal): string {
  return goal.period_type === 'monthly' ? `${goal.year} 年 ${goal.month} 月` : `${goal.year} 年度`
}

function openCreate() {
  editingId.value = null
  Object.assign(form, {
    period_type: 'monthly',
    year: now.getFullYear(),
    month: now.getMonth() + 1,
    amount: '',
  })
  formError.value = ''
  dialog.value?.showModal()
}

function openEdit(goal: SavingsGoal) {
  editingId.value = goal.id
  Object.assign(form, {
    period_type: goal.period_type,
    year: goal.year,
    month: goal.month ?? now.getMonth() + 1,
    amount: goal.amount,
  })
  formError.value = ''
  dialog.value?.showModal()
}

const AMOUNT_RE = /^\d+(\.\d{1,2})?$/
function validate(): boolean {
  if (!AMOUNT_RE.test(form.amount) || Number(form.amount) <= 0) {
    formError.value = '金額需為大於 0 的數字（至多兩位小數）'
    return false
  }
  if (form.period_type === 'monthly' && (form.month < 1 || form.month > 12)) {
    formError.value = '月度目標的月份需為 1–12'
    return false
  }
  return true
}

async function submit() {
  formError.value = ''
  if (!validate()) return
  // 年度目標不帶 month（後端拒年度帶 month）；月度才送 month。
  const body = {
    period_type: form.period_type,
    year: form.year,
    month: form.period_type === 'monthly' ? form.month : null,
    amount: form.amount,
  } satisfies GoalWrite as unknown as SavingsGoal
  const { error } = editingId.value
    ? await api.PATCH('/api/ledger/savings-goals/{id}/', {
        params: { path: { id: editingId.value } },
        body,
      })
    : await api.POST('/api/ledger/savings-goals/', { body })
  if (error) {
    formError.value = messagesFrom(error) // 唯一性 400「此期間已有儲蓄目標」如實顯示
    return
  }
  dialog.value?.close()
  await load()
  toast('已儲存')
}

function askDelete(id: string) {
  pendingDeleteId.value = id
  deleteDialog.value?.showModal()
}

async function confirmDelete() {
  deleteDialog.value?.close()
  const id = pendingDeleteId.value
  if (!id) return
  const { error } = await api.DELETE('/api/ledger/savings-goals/{id}/', {
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
      data-test="goal-new"
      class="bg-brand-fill self-start rounded-lg px-3 py-1.5 text-sm text-white"
      @click="openCreate"
    >
      新增儲蓄目標
    </button>

    <p v-if="goals.length === 0" class="text-ink-2 py-6 text-center text-sm">尚無儲蓄目標</p>

    <ul v-else class="flex flex-col gap-2">
      <li
        v-for="goal in goals"
        :key="goal.id"
        data-test="goal-row"
        class="bg-card rounded-card flex items-center justify-between gap-2 px-4 py-3"
      >
        <p class="text-ink">{{ periodLabel(goal) }}</p>
        <div class="flex shrink-0 items-center gap-3 text-xs">
          <UiAmount :value="goal.amount" class="text-ink text-sm" />
          <button type="button" data-test="goal-edit" class="text-ink-2" @click="openEdit(goal)">
            編輯
          </button>
          <button
            type="button"
            data-test="goal-delete"
            class="text-expense"
            @click="askDelete(goal.id)"
          >
            刪除
          </button>
        </div>
      </li>
    </ul>

    <!-- 新增／編輯共用 dialog -->
    <dialog ref="dialog" class="rounded-card m-auto w-80 max-w-[90vw] p-5 backdrop:bg-black/30">
      <form class="flex flex-col gap-3" @submit.prevent="submit">
        <h2 class="font-medium">{{ editingId ? '編輯儲蓄目標' : '新增儲蓄目標' }}</h2>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">週期</span>
          <select
            v-model="form.period_type"
            data-test="goal-period"
            class="border-hairline rounded-lg border px-3 py-2"
          >
            <option value="monthly">月度</option>
            <option value="yearly">年度</option>
          </select>
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">年份</span>
          <input
            v-model.number="form.year"
            data-test="goal-year"
            type="number"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>

        <label v-if="form.period_type === 'monthly'" class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">月份</span>
          <input
            v-model.number="form.month"
            data-test="goal-month"
            type="number"
            min="1"
            max="12"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">目標金額</span>
          <input
            v-model="form.amount"
            data-test="goal-amount"
            inputmode="decimal"
            placeholder="0.00"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>

        <p v-if="formError" data-test="goal-error" class="text-expense text-sm">{{ formError }}</p>
        <div class="flex justify-end gap-2">
          <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="dialog?.close()">
            取消
          </button>
          <button
            type="submit"
            data-test="goal-submit"
            class="bg-brand-fill rounded-lg px-3 py-1.5 text-sm text-white"
          >
            儲存
          </button>
        </div>
      </form>
    </dialog>

    <!-- 刪除確認 -->
    <dialog ref="deleteDialog" class="rounded-card m-auto p-5 backdrop:bg-black/30">
      <p class="mb-4">確定刪除此儲蓄目標？</p>
      <div class="flex justify-end gap-2">
        <button type="button" class="text-ink-2 px-3 py-1.5 text-sm" @click="deleteDialog?.close()">
          取消
        </button>
        <button
          type="button"
          data-test="goal-confirm-delete"
          class="bg-expense dark:text-bg rounded-lg px-3 py-1.5 text-sm text-white"
          @click="confirmDelete"
        >
          刪除
        </button>
      </div>
    </dialog>
  </div>
</template>
