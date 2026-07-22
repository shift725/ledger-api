<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { useReferenceStore } from '@/stores/reference'
import { toDatetimeLocal } from '@/lib/format'
import { toast } from '@/lib/toast'
import { messagesFrom } from '@/lib/errors'
import Card from '@/components/ui/UiCard.vue'

type Transfer = components['schemas']['Transfer']

const router = useRouter()
const reference = useReferenceStore()

const form = reactive({
  fromAccount: '',
  toAccount: '',
  amount: '', // 無手續費模式：單一金額
  fromAmount: '', // 有手續費：出帳
  toAmount: '', // 有手續費：入帳
  occurredAt: toDatetimeLocal(new Date()),
  name: '',
  description: '',
})
const hasFee = ref(false)
const showMore = ref(false)
const amountError = ref('')
const accountError = ref('')
const serverError = ref('')

// 至少兩個帳戶才談得上轉帳（否則轉出＝轉入）。
const enoughAccounts = computed(() => reference.accounts.length >= 2)

onMounted(async () => {
  await reference.ensure()
  const def = reference.accounts.find((a) => a.is_default) ?? reference.accounts[0]
  if (def) form.fromAccount = def.id
  const other = reference.accounts.find((a) => a.id !== form.fromAccount)
  if (other) form.toAccount = other.id
})

// 切到「有手續費」：入帳預帶＝出帳（多數轉帳無手續費，有才手動改小）。
watch(hasFee, (on) => {
  if (on) {
    form.fromAmount = form.amount
    form.toAmount = form.amount
  } else {
    form.amount = form.fromAmount
  }
})

const AMOUNT_RE = /^\d+(\.\d{1,2})?$/
function positive(v: string): boolean {
  return AMOUNT_RE.test(v) && Number(v) > 0
}

// 回兩腿金額字串，或 null（驗證失敗、已設 amountError）。
function resolveAmounts(): { from: string; to: string } | null {
  amountError.value = ''
  if (!hasFee.value) {
    if (!positive(form.amount)) {
      amountError.value = '金額需為大於 0 的數字（至多兩位小數）'
      return null
    }
    return { from: form.amount, to: form.amount } // 無手續費：出帳＝入帳
  }
  if (!positive(form.fromAmount) || !positive(form.toAmount)) {
    amountError.value = '出帳與入帳金額需為大於 0 的數字（至多兩位小數）'
    return null
  }
  if (Number(form.fromAmount) < Number(form.toAmount)) {
    amountError.value = '入帳金額不可大於出帳金額（差額為手續費）'
    return null
  }
  return { from: form.fromAmount, to: form.toAmount }
}

async function submit() {
  serverError.value = ''
  accountError.value = form.fromAccount === form.toAccount ? '轉出與轉入不可為同一帳戶' : ''
  const amounts = resolveAmounts()
  if (accountError.value || !amounts) return

  const body = {
    from_account: form.fromAccount,
    to_account: form.toAccount,
    from_amount: amounts.from,
    to_amount: amounts.to,
    occurred_at: new Date(form.occurredAt).toISOString(), // 明送 instant
    name: form.name,
    description: form.description,
  } satisfies Transfer

  let result
  try {
    result = await api.POST('/api/ledger/transactions/transfer/', { body })
  } catch {
    // fetch 直接炸＝離線。轉帳的兩腿原子性靠後端單一交易保證，需連線，故不入離線佇列。
    serverError.value = '目前離線，無法轉帳。請恢復連線後再試。'
    return
  }
  const submitError: unknown = result.error
  if (submitError) {
    serverError.value = messagesFrom(submitError)
    return
  }
  await reference.refresh() // 兩帳戶餘額已變 → 重抓參照資料
  toast('已轉帳')
  router.push('/transactions')
}
</script>

<template>
  <header class="mb-3.5 flex items-baseline justify-between">
    <h1 class="text-xl font-medium">轉帳</h1>
    <RouterLink to="/transactions/new" class="text-brand-text text-sm">改為記一筆</RouterLink>
  </header>

  <p v-if="!enoughAccounts" class="text-ink-2 py-10 text-center">
    轉帳需要至少兩個帳戶，請先到「更多 → 帳戶」新增後再操作。
  </p>

  <form v-else class="flex flex-col gap-2.5" @submit.prevent="submit">
    <Card class="flex flex-col gap-3">
      <!-- 轉出帳戶 -->
      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">轉出帳戶</span>
        <select
          v-model="form.fromAccount"
          data-test="from-account"
          class="border-hairline rounded-lg border px-3 py-2"
        >
          <option v-for="a in reference.accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select>
      </label>

      <!-- 轉入帳戶 -->
      <label class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">轉入帳戶</span>
        <select
          v-model="form.toAccount"
          data-test="to-account"
          class="border-hairline rounded-lg border px-3 py-2"
        >
          <option v-for="a in reference.accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
        </select>
        <span v-if="accountError" data-test="account-error" class="text-expense text-sm">{{
          accountError
        }}</span>
      </label>

      <!-- 金額：無手續費＝單欄；有手續費＝出帳／入帳兩欄 -->
      <label v-if="!hasFee" class="flex flex-col gap-1">
        <span class="text-ink-2 text-sm">金額</span>
        <input
          v-model="form.amount"
          data-test="amount"
          inputmode="decimal"
          placeholder="0.00"
          class="border-hairline rounded-lg border px-3 py-2 text-lg"
        />
      </label>
      <template v-else>
        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">出帳金額</span>
          <input
            v-model="form.fromAmount"
            data-test="from-amount"
            inputmode="decimal"
            placeholder="0.00"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-ink-2 text-sm">入帳金額</span>
          <input
            v-model="form.toAmount"
            data-test="to-amount"
            inputmode="decimal"
            placeholder="0.00"
            class="border-hairline rounded-lg border px-3 py-2"
          />
        </label>
      </template>
      <span v-if="amountError" data-test="amount-error" class="text-expense text-sm">{{
        amountError
      }}</span>

      <!-- 有手續費開關 -->
      <label class="flex items-center gap-2 text-sm">
        <input v-model="hasFee" data-test="has-fee" type="checkbox" />
        <span class="text-ink-2">有手續費（出帳與入帳金額不同）</span>
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

    <!-- 次層：備註 -->
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
        <span class="text-ink-2 text-sm">名稱</span>
        <input
          v-model="form.name"
          data-test="transfer-name"
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

    <p v-if="serverError" data-test="transfer-error" class="text-expense text-sm">
      {{ serverError }}
    </p>

    <button
      type="submit"
      data-test="transfer-submit"
      class="bg-brand-fill rounded-lg py-2.5 font-medium text-white"
    >
      轉帳
    </button>
  </form>
</template>
