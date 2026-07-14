import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import SimpleResourceSection from '@/components/settings/SimpleResourceSection.vue'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

// 分類/標籤同形，共用同一元件、同一組測試參數化——兩者行為契約一致。
const RESOURCES = [
  { resource: 'categories' as const, path: 'categories', names: ['餐飲', '居住', '薪水'] },
  { resource: 'tags' as const, path: 'tags', names: ['固定支出', '訂閱'] },
]

async function mountSection(resource: 'categories' | 'tags'): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const wrapper = mount(SimpleResourceSection, {
    props: { resource },
    global: { plugins: [pinia] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe.each(RESOURCES)('SimpleResourceSection — $resource', ({ resource, path, names }) => {
  it('列出各項名稱', async () => {
    const wrapper = await mountSection(resource)
    expect(wrapper.findAll('[data-test="res-row"]')).toHaveLength(names.length)
    for (const name of names) expect(wrapper.text()).toContain(name)
  })

  it('新增送出 POST {name, description} → 成功 toast', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.post(`*/api/ledger/${path}/`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...body, id: 'new-1' }, { status: 201 })
      }),
    )
    const wrapper = await mountSection(resource)
    await wrapper.find('[data-test="res-new"]').trigger('click')
    await wrapper.find('[data-test="res-name"]').setValue('新項目')
    await wrapper.find('[data-test="res-desc"]').setValue('說明文字')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).toEqual({ name: '新項目', description: '說明文字' })
    expect(toastMessage.value).toContain('已儲存')
  })

  it('重名 400 逐欄如實顯示', async () => {
    server.use(
      http.post(`*/api/ledger/${path}/`, () =>
        HttpResponse.json({ name: ['此名稱已使用'] }, { status: 400 }),
      ),
    )
    const wrapper = await mountSection(resource)
    await wrapper.find('[data-test="res-new"]').trigger('click')
    await wrapper.find('[data-test="res-name"]').setValue('重複')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="res-error"]').text()).toContain('此名稱已使用')
  })

  it('刪除 204 → 已刪除 toast', async () => {
    server.use(
      http.delete(`*/api/ledger/${path}/:id`, () => new HttpResponse(null, { status: 204 })),
    )
    const wrapper = await mountSection(resource)
    await wrapper.findAll('[data-test="res-delete"]')[0]!.trigger('click')
    await wrapper.find('[data-test="res-confirm-delete"]').trigger('click')
    await flushPromises()

    expect(toastMessage.value).toContain('已刪除')
  })
})
