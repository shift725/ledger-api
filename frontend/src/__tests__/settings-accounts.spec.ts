import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import AccountsSection from '@/components/settings/AccountsSection.vue'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

// 罐頭 GET accounts（handlers 預設）：acc-1 現金 is_default、acc-2 台新 bank。
async function mountSection(): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const wrapper = mount(AccountsSection, { global: { plugins: [pinia] } })
  await flushPromises() // ensure() 載入 reference 三清單
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe('AccountsSection — 列表', () => {
  it('渲染每帳戶的類型標籤、格式化餘額、預設徽章（恰一個）', async () => {
    const wrapper = await mountSection()
    expect(wrapper.findAll('[data-test="account-row"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('現金')
    expect(wrapper.text()).toContain('銀行')
    expect(wrapper.text()).toContain('12,350.00') // 餘額千分位（唯讀顯示）
    expect(wrapper.findAll('[data-test="account-default-badge"]')).toHaveLength(1)
  })
})

describe('AccountsSection — 新增', () => {
  it('填表送出 POST（剝唯讀欄）→ 成功 toast', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post('*/api/ledger/accounts/', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...body, id: 'new-1', balance: '0.00' }, { status: 201 })
      }),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="account-new"]').trigger('click')
    await wrapper.find('[data-test="account-name"]').setValue('信用卡A')
    await wrapper.find('[data-test="account-type"]').setValue('credit_card')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).toMatchObject({ name: '信用卡A', type: 'credit_card', is_default: false })
    expect(body).not.toHaveProperty('id') // 唯讀衍生欄未送
    expect(body).not.toHaveProperty('balance')
    expect(toastMessage.value).toContain('已儲存')
  })

  it('重名 400 逐欄如實顯示、dialog 不關', async () => {
    server.use(
      http.post('*/api/ledger/accounts/', () =>
        HttpResponse.json({ name: ['此名稱已使用'] }, { status: 400 }),
      ),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="account-new"]').trigger('click')
    await wrapper.find('[data-test="account-name"]').setValue('現金')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="account-error"]').text()).toContain('此名稱已使用')
  })
})

describe('AccountsSection — is_default 切換', () => {
  it('設非預設帳戶為預設 → PATCH 本筆；重抓後恰一預設', async () => {
    let patchedId: string | readonly string[] | undefined
    let patchBody: Record<string, unknown> | null = null
    // 有狀態 handler：GET 依 defaulted 算 is_default（mount 時 acc-1 預設），PATCH 翻轉它，
    // 重抓時反映新預設 → 驗「單選語意＋重抓後恰一預設」。
    let defaulted = 'acc-1'
    server.use(
      http.patch('*/api/ledger/accounts/:id', async ({ request, params }) => {
        patchedId = params.id
        patchBody = (await request.json()) as Record<string, unknown>
        defaulted = String(params.id)
        return HttpResponse.json({ id: params.id, ...patchBody })
      }),
      http.get('*/api/ledger/accounts/', () =>
        HttpResponse.json({
          count: 2,
          next: null,
          previous: null,
          results: [
            {
              id: 'acc-1',
              name: '現金',
              type: 'cash',
              balance: '12350.00',
              is_default: defaulted === 'acc-1',
            },
            {
              id: 'acc-2',
              name: '台新銀行',
              type: 'bank',
              balance: '236000.00',
              is_default: defaulted === 'acc-2',
            },
          ],
        }),
      ),
    )
    const wrapper = await mountSection()
    await wrapper.find('[data-test="account-set-default"]').trigger('click') // acc-2（唯一非預設）
    await flushPromises()

    expect(patchedId).toBe('acc-2')
    expect(patchBody).toEqual({ is_default: true })
    expect(wrapper.findAll('[data-test="account-default-badge"]')).toHaveLength(1)
  })
})

describe('AccountsSection — 刪除', () => {
  it('有交易的帳戶 409 → 顯示後端 detail 人話', async () => {
    server.use(
      http.delete('*/api/ledger/accounts/:id', () =>
        HttpResponse.json({ detail: '帳戶尚有交易或定期定額規則，無法刪除' }, { status: 409 }),
      ),
    )
    const wrapper = await mountSection()
    await wrapper.findAll('[data-test="account-delete"]')[0]!.trigger('click')
    await wrapper.find('[data-test="account-confirm-delete"]').trigger('click')
    await flushPromises()

    expect(toastMessage.value).toContain('無法刪除')
  })

  it('空帳戶刪除 204 → 已刪除 toast', async () => {
    server.use(
      http.delete('*/api/ledger/accounts/:id', () => new HttpResponse(null, { status: 204 })),
    )
    const wrapper = await mountSection()
    await wrapper.findAll('[data-test="account-delete"]')[0]!.trigger('click')
    await wrapper.find('[data-test="account-confirm-delete"]').trigger('click')
    await flushPromises()

    expect(toastMessage.value).toContain('已刪除')
  })
})
