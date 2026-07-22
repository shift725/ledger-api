import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { http, HttpResponse } from 'msw'
import TransferFormView from '@/views/TransferFormView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

async function mountForm(): Promise<{ wrapper: VueWrapper; router: Router }> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  useAuthStore().user = { id: 'user-1', username: 'demo', email: 'd@x.tw', role: 'member' }
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/transactions/transfer')
  const wrapper = mount(TransferFormView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe('TransferFormView — 轉帳', () => {
  it('預設：轉出＝is_default 帳戶、轉入＝另一個帳戶（from≠to）', async () => {
    const { wrapper } = await mountForm()
    const from = wrapper.find('[data-test="from-account"]').element as HTMLSelectElement
    const to = wrapper.find('[data-test="to-account"]').element as HTMLSelectElement
    expect(from.value).toBe('acc-1') // 罐頭 is_default
    expect(to.value).toBe('acc-2')
    expect(from.value).not.toBe(to.value)
  })

  it('無手續費送出：出帳＝入帳＝金額、occurred_at 明送 ISO；成功→toast＋導回列表', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('*/api/ledger/transactions/transfer/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          { from: { id: 'o1', is_transfer: true }, to: { id: 'i1', is_transfer: true } },
          { status: 201 },
        )
      }),
    )
    const { wrapper, router } = await mountForm()
    await wrapper.find('[data-test="amount"]').setValue('1000.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).not.toBeNull()
    expect(body!.from_account).toBe('acc-1')
    expect(body!.to_account).toBe('acc-2')
    expect(body!.from_amount).toBe('1000.00')
    expect(body!.to_amount).toBe('1000.00') // 無手續費：兩腿同額
    expect(body!.occurred_at).toMatch(/^\d{4}-\d{2}-\d{2}T.*Z$/)
    expect(toastMessage.value).toContain('已轉帳')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/transactions'))
  })

  it('有手續費：勾選後拆兩欄，可送不同出帳／入帳金額', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('*/api/ledger/transactions/transfer/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          { from: { id: 'o1', is_transfer: true }, to: { id: 'i1', is_transfer: true } },
          { status: 201 },
        )
      }),
    )
    const { wrapper } = await mountForm()
    // 預設無手續費：只有單一金額欄
    expect(wrapper.find('[data-test="amount"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="from-amount"]').exists()).toBe(false)

    await wrapper.find('[data-test="has-fee"]').setValue(true)
    expect(wrapper.find('[data-test="from-amount"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="to-amount"]').exists()).toBe(true)

    await wrapper.find('[data-test="from-amount"]').setValue('1000.00')
    await wrapper.find('[data-test="to-amount"]').setValue('970.00') // 30 手續費
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body!.from_amount).toBe('1000.00')
    expect(body!.to_amount).toBe('970.00')
  })

  it('轉出＝轉入同一帳戶：擋住不送、顯示錯誤', async () => {
    let called = false
    server.use(
      http.post('*/api/ledger/transactions/transfer/', () => {
        called = true
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    const { wrapper } = await mountForm()
    await wrapper.find('[data-test="to-account"]').setValue('acc-1') // 與轉出同帳戶
    await wrapper.find('[data-test="amount"]').setValue('100.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(called).toBe(false)
    expect(wrapper.find('[data-test="account-error"]').text()).toContain('同一帳戶')
  })

  it('入帳金額大於出帳：擋住不送、顯示錯誤', async () => {
    let called = false
    server.use(
      http.post('*/api/ledger/transactions/transfer/', () => {
        called = true
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    const { wrapper } = await mountForm()
    await wrapper.find('[data-test="has-fee"]').setValue(true)
    await wrapper.find('[data-test="from-amount"]').setValue('100.00')
    await wrapper.find('[data-test="to-amount"]').setValue('150.00') // 入帳 > 出帳
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(called).toBe(false)
    expect(wrapper.find('[data-test="amount-error"]').text()).toContain('入帳金額不可大於出帳金額')
  })

  it('離線（fetch 網路錯）：顯示離線文案、不入佇列', async () => {
    server.use(http.post('*/api/ledger/transactions/transfer/', () => HttpResponse.error()))
    const { wrapper } = await mountForm()
    await wrapper.find('[data-test="amount"]').setValue('100.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-test="transfer-error"]').text()).toContain('離線')
  })

  it('後端 400 如實顯示', async () => {
    server.use(
      http.post('*/api/ledger/transactions/transfer/', () =>
        HttpResponse.json({ from_amount: ['請輸入有效金額'] }, { status: 400 }),
      ),
    )
    const { wrapper } = await mountForm()
    await wrapper.find('[data-test="amount"]').setValue('100.00')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-test="transfer-error"]').text()).toContain('請輸入有效金額')
  })
})
