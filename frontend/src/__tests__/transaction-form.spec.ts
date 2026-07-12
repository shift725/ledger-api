import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { http, HttpResponse } from 'msw'
import TransactionFormView from '@/views/TransactionFormView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

async function mountForm(path: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(path)
  const wrapper = mount(TransactionFormView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe('TransactionFormView — 記一筆', () => {
  it('預設值：帳戶＝is_default、收支＝expense、occurred_at 預填現在', async () => {
    const { wrapper } = await mountForm('/transactions/new')
    const account = wrapper.find('select[data-test="form-account"]').element as HTMLSelectElement
    expect(account.value).toBe('acc-1') // 罐頭 is_default
    const dt = wrapper.find('input[type="datetime-local"]').element as HTMLInputElement
    expect(dt.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/) // 預填現在
  })

  it('送出 payload：occurred_at 明送 ISO＋必填欄；成功→toast＋導回列表', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('*/api/ledger/transactions/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...body, id: 'new-1' }, { status: 201 })
      }),
    )
    const { wrapper, router } = await mountForm('/transactions/new')
    await wrapper.find('input[data-test="form-amount"]').setValue('123.45')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).not.toBeNull()
    expect(body!.amount).toBe('123.45')
    expect(body!.type).toBe('expense')
    expect(body!.account).toBe('acc-1')
    expect(body!.occurred_at).toMatch(/^\d{4}-\d{2}-\d{2}T.*Z$/) // 明送 ISO instant
    // 送出 body 不含唯讀衍生欄（TransactionWrite Omit）
    expect(body).not.toHaveProperty('source_rule')
    expect(body).not.toHaveProperty('account_name')
    expect(toastMessage.value).toContain('已儲存')
    // 導向的是 lazy route（() => import），需等動態載入完成
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/transactions'))
  })

  it('金額非法（負數）擋住不送、顯示錯誤', async () => {
    let called = false
    server.use(
      http.post('*/api/ledger/transactions/', () => {
        called = true
        return HttpResponse.json({ id: 'x' }, { status: 201 })
      }),
    )
    const { wrapper } = await mountForm('/transactions/new')
    await wrapper.find('input[data-test="form-amount"]').setValue('-5')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(called).toBe(false)
    expect(wrapper.text()).toContain('金額')
  })

  it('金額超過兩位小數擋住', async () => {
    let called = false
    server.use(
      http.post('*/api/ledger/transactions/', () => {
        called = true
        return HttpResponse.json({ id: 'x' }, { status: 201 })
      }),
    )
    const { wrapper } = await mountForm('/transactions/new')
    await wrapper.find('input[data-test="form-amount"]').setValue('12.345')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(called).toBe(false)
  })

  it('後端 400 如實顯示', async () => {
    server.use(
      http.post('*/api/ledger/transactions/', () =>
        HttpResponse.json({ amount: ['金額必須大於 0'] }, { status: 400 }),
      ),
    )
    const { wrapper } = await mountForm('/transactions/new')
    await wrapper.find('input[data-test="form-amount"]').setValue('100')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('金額必須大於 0')
  })

  it('次層收合：更多欄位預設隱藏、展開後可填 name', async () => {
    const { wrapper } = await mountForm('/transactions/new')
    expect(wrapper.find('input[data-test="form-name"]').exists()).toBe(false)
    await wrapper.find('[data-test="toggle-more"]').trigger('click')
    expect(wrapper.find('input[data-test="form-name"]').exists()).toBe(true)
  })
})

const editable = {
  id: 'txn-1',
  account: 'acc-2',
  category: 'cat-food',
  amount: '250.00',
  type: 'income',
  name: '獎金',
  description: 'desc',
  occurred_at: '2026-07-08T09:30:00+08:00',
  tags: ['tag-1'],
  source_rule: null,
  account_name: '台新銀行',
  category_name: '餐飲',
  tag_names: ['固定支出'],
}

describe('TransactionFormView — 編輯／刪除', () => {
  it('編輯：GET 預填各欄，次層有值時自動展開', async () => {
    server.use(http.get('*/api/ledger/transactions/:id', () => HttpResponse.json(editable)))
    const { wrapper } = await mountForm('/transactions/txn-1')
    expect((wrapper.find('[data-test="form-amount"]').element as HTMLInputElement).value).toBe(
      '250.00',
    )
    expect((wrapper.find('[data-test="form-account"]').element as HTMLSelectElement).value).toBe(
      'acc-2',
    )
    expect((wrapper.find('[data-test="form-name"]').element as HTMLInputElement).value).toBe('獎金')
  })

  it('不存在／跨用戶 → 404 → 顯示找不到、無權限字眼、無送出鈕', async () => {
    server.use(
      http.get('*/api/ledger/transactions/:id', () => new HttpResponse(null, { status: 404 })),
    )
    const { wrapper } = await mountForm('/transactions/nope')
    expect(wrapper.text()).toContain('找不到')
    expect(wrapper.text()).not.toContain('權限')
    expect(wrapper.find('[data-test="form-submit"]').exists()).toBe(false)
  })

  it('儲存＝PATCH /{id}/ 全可編輯欄；category 選未分類、tags 取消 → 送 null／[]', async () => {
    server.use(http.get('*/api/ledger/transactions/:id', () => HttpResponse.json(editable)))
    let patchBody: Record<string, unknown> | null = null
    server.use(
      http.patch('*/api/ledger/transactions/:id', async ({ request }) => {
        patchBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...editable, ...patchBody })
      }),
    )
    const { wrapper, router } = await mountForm('/transactions/txn-1')
    await wrapper.find('[data-test="form-amount"]').setValue('300.00')
    await wrapper.find('[data-test="form-category"]').setValue('') // 未分類
    // 取消已勾的 tag-1
    const checked = wrapper
      .findAll('input[type="checkbox"]')
      .find((c) => (c.element as HTMLInputElement).checked)
    await checked!.setValue(false)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(patchBody).not.toBeNull()
    expect(patchBody!.amount).toBe('300.00')
    expect(patchBody!.category).toBeNull()
    expect(patchBody!.tags).toEqual([])
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/transactions'))
  })

  it('刪除：dialog 確認 → DELETE → toast＋導回列表', async () => {
    server.use(http.get('*/api/ledger/transactions/:id', () => HttpResponse.json(editable)))
    let deleted = false
    server.use(
      http.delete('*/api/ledger/transactions/:id', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { wrapper, router } = await mountForm('/transactions/txn-1')
    await wrapper.find('[data-test="open-delete"]').trigger('click')
    await wrapper.find('[data-test="confirm-delete"]').trigger('click')
    await flushPromises()

    expect(deleted).toBe(true)
    expect(toastMessage.value).toContain('已刪除')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/transactions'))
  })
})
