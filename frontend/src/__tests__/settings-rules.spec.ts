import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import RulesSection from '@/components/settings/RulesSection.vue'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

const baseRule = {
  id: 'rule-1',
  account: 'acc-1',
  account_name: '現金',
  category: null,
  category_name: null,
  amount: '1000.00',
  type: 'expense',
  name: '房租',
  description: '',
  day_of_month: 5,
  is_active: true,
  next_run_date: '2026-08-05',
}

function listOf(rules: unknown[]) {
  return http.get('*/api/ledger/recurring-rules/', () =>
    HttpResponse.json({ count: rules.length, next: null, previous: null, results: rules }),
  )
}

async function mountSection(): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const wrapper = mount(RulesSection, { global: { plugins: [pinia] } })
  await flushPromises() // reference.ensure() ＋ 自抓 rules
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe('RulesSection — 列表', () => {
  it('顯示名稱、每月扣款日、唯讀下次日期、停用語意文案', async () => {
    server.use(listOf([baseRule]))
    const wrapper = await mountSection()
    expect(wrapper.findAll('[data-test="rule-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('房租')
    expect(wrapper.text()).toContain('每月 5 號')
    expect(wrapper.text()).toContain('2026-08-05') // next_run_date 唯讀
    expect(wrapper.text()).toContain('停用期間不補記') // 停機語意如實傳達給使用者
  })
})

describe('RulesSection — 新增', () => {
  it('填必填欄送出 POST（含 day_of_month 數字）→ 成功 toast', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      listOf([]),
      http.post('*/api/ledger/recurring-rules/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...baseRule, ...body, id: 'new-1' }, { status: 201 })
      }),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="rule-new"]').trigger('click')
    await wrapper.find('[data-test="rule-amount"]').setValue('1500.00')
    await wrapper.find('[data-test="rule-day"]').setValue(10)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).toMatchObject({
      account: 'acc-1', // 預設 is_default 帳戶
      amount: '1500.00',
      type: 'expense',
      day_of_month: 10,
    })
    expect(toastMessage.value).toContain('已儲存')
  })

  it('扣款日超出 1–31 前端擋住不送', async () => {
    let called = false
    server.use(
      listOf([]),
      http.post('*/api/ledger/recurring-rules/', () => {
        called = true
        return HttpResponse.json({ id: 'x' }, { status: 201 })
      }),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="rule-new"]').trigger('click')
    await wrapper.find('[data-test="rule-amount"]').setValue('100')
    await wrapper.find('[data-test="rule-day"]').setValue(40)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(called).toBe(false)
    expect(wrapper.find('[data-test="rule-error"]').text()).toContain('扣款日')
  })
})

describe('RulesSection — is_active 開關', () => {
  it('停用→重新啟用：PATCH is_active，重啟後 next_run_date 從今日重算', async () => {
    let active = true
    let nextDate = '2026-08-05'
    const patchBodies: Record<string, unknown>[] = []
    server.use(
      http.patch('*/api/ledger/recurring-rules/:id', async ({ request }) => {
        const b = (await request.json()) as { is_active: boolean }
        patchBodies.push(b)
        active = b.is_active
        if (active) nextDate = '2026-07-14' // 後端重啟用時從今日重算
        return HttpResponse.json({ ...baseRule, is_active: active, next_run_date: nextDate })
      }),
      http.get('*/api/ledger/recurring-rules/', () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [{ ...baseRule, is_active: active, next_run_date: nextDate }],
        }),
      ),
    )
    const wrapper = await mountSection()
    expect(wrapper.find('[data-test="rule-active-toggle"]').text()).toBe('停用')

    await wrapper.find('[data-test="rule-active-toggle"]').trigger('click') // 停用
    await flushPromises()
    expect(wrapper.text()).toContain('已停用')
    expect(wrapper.find('[data-test="rule-active-toggle"]').text()).toBe('啟用')

    await wrapper.find('[data-test="rule-active-toggle"]').trigger('click') // 重新啟用
    await flushPromises()
    expect(patchBodies).toEqual([{ is_active: false }, { is_active: true }])
    expect(wrapper.text()).toContain('2026-07-14') // 重算後的新下次日期
  })
})

describe('RulesSection — 刪除', () => {
  it('刪除 204 → 已刪除 toast', async () => {
    server.use(
      listOf([baseRule]),
      http.delete(
        '*/api/ledger/recurring-rules/:id',
        () => new HttpResponse(null, { status: 204 }),
      ),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="rule-delete"]').trigger('click')
    await wrapper.find('[data-test="rule-confirm-delete"]').trigger('click')
    await flushPromises()

    expect(toastMessage.value).toContain('已刪除')
  })
})
