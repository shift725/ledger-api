import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import GoalsSection from '@/components/settings/GoalsSection.vue'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

const monthlyGoal = {
  id: 'goal-1',
  period_type: 'monthly',
  year: 2026,
  month: 7,
  amount: '20000.00',
}

function listOf(goals: unknown[]) {
  return http.get('*/api/ledger/savings-goals/', () =>
    HttpResponse.json({ count: goals.length, next: null, previous: null, results: goals }),
  )
}

async function mountSection(): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const wrapper = mount(GoalsSection, { global: { plugins: [pinia] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe('GoalsSection — 列表', () => {
  it('月度目標顯示年月與金額', async () => {
    server.use(listOf([monthlyGoal]))
    const wrapper = await mountSection()
    expect(wrapper.findAll('[data-test="goal-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('2026 年 7 月')
    expect(wrapper.text()).toContain('20,000')
  })
})

describe('GoalsSection — 新增', () => {
  it('月度：送出 period_type/year/month/amount', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      listOf([]),
      http.post('*/api/ledger/savings-goals/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...body, id: 'new-1' }, { status: 201 })
      }),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="goal-new"]').trigger('click')
    await wrapper.find('[data-test="goal-amount"]').setValue('30000.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).toMatchObject({ period_type: 'monthly', amount: '30000.00' })
    expect(typeof body!.month).toBe('number')
    expect(toastMessage.value).toContain('已儲存')
  })

  it('年度：隱藏月份欄，且 month 送 null', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      listOf([]),
      http.post('*/api/ledger/savings-goals/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...body, id: 'new-1' }, { status: 201 })
      }),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="goal-new"]').trigger('click')
    await wrapper.find('[data-test="goal-period"]').setValue('yearly')
    expect(wrapper.find('[data-test="goal-month"]').exists()).toBe(false)
    await wrapper.find('[data-test="goal-amount"]').setValue('240000.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).toMatchObject({ period_type: 'yearly', month: null })
  })

  it('唯一性 400 如實顯示', async () => {
    server.use(
      listOf([]),
      http.post('*/api/ledger/savings-goals/', () =>
        HttpResponse.json({ non_field_errors: ['此期間已有儲蓄目標'] }, { status: 400 }),
      ),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="goal-new"]').trigger('click')
    await wrapper.find('[data-test="goal-amount"]').setValue('20000.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="goal-error"]').text()).toContain('此期間已有儲蓄目標')
  })
})

describe('GoalsSection — 刪除', () => {
  it('刪除 204 → 已刪除 toast', async () => {
    server.use(
      listOf([monthlyGoal]),
      http.delete('*/api/ledger/savings-goals/:id', () => new HttpResponse(null, { status: 204 })),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="goal-delete"]').trigger('click')
    await wrapper.find('[data-test="goal-confirm-delete"]').trigger('click')
    await flushPromises()

    expect(toastMessage.value).toContain('已刪除')
  })
})
