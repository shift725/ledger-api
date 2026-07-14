import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import ProfileSection from '@/components/settings/ProfileSection.vue'
import { useAuthStore } from '@/stores/auth'
import { toastMessage } from '@/lib/toast'
import { server } from '@/mocks/node'

async function mountSection(): Promise<{
  wrapper: VueWrapper
  store: ReturnType<typeof useAuthStore>
}> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore()
  await store.login('demo@example.com', 'pw') // 罐頭 → user id=user-1、access
  const wrapper = mount(ProfileSection, { global: { plugins: [pinia] } })
  await flushPromises() // GET users/{id}
  return { wrapper, store }
}

function inputValue(wrapper: VueWrapper, sel: string): string {
  return (wrapper.find(sel).element as HTMLInputElement).value
}

beforeEach(() => {
  localStorage.clear()
  toastMessage.value = ''
})

describe('ProfileSection — 檢視', () => {
  it('GET 帶出帳號/Email/電話/身分/註冊日', async () => {
    server.use(
      http.get('*/api/auth/users/:id', () =>
        HttpResponse.json({
          id: 'user-1',
          username: 'demo',
          email: 'demo@example.com',
          phone: '0912345678',
          role: 'member',
          created_at: '2026-07-12T00:00:00Z',
        }),
      ),
    )
    const { wrapper } = await mountSection()
    expect(inputValue(wrapper, '[data-test="profile-username"]')).toBe('demo')
    expect(inputValue(wrapper, '[data-test="profile-email"]')).toBe('demo@example.com')
    expect(inputValue(wrapper, '[data-test="profile-phone"]')).toBe('0912345678')
    expect(wrapper.find('[data-test="profile-role"]').text()).toBe('會員') // 顯示不可編
    expect(wrapper.text()).toContain('2026-07-12')
  })
})

describe('ProfileSection — 編輯', () => {
  it('PATCH 成功 → toast＋同步 auth store 的 username', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      http.patch('*/api/auth/users/:id', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({
          id: 'user-1',
          username: body.username,
          email: body.email,
          phone: body.phone,
          role: 'member',
          created_at: '2026-07-12T00:00:00Z',
        })
      }),
    )
    const { wrapper, store } = await mountSection()
    await wrapper.find('[data-test="profile-username"]').setValue('newname')
    await wrapper.find('[data-test="profile-phone"]').setValue('0900000000')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body).toMatchObject({ username: 'newname', phone: '0900000000' })
    expect(toastMessage.value).toContain('已儲存')
    expect(store.user?.username).toBe('newname') // 殼即時反映
  })

  it('後端 400（帳號已被使用）逐欄如實顯示', async () => {
    server.use(
      http.patch('*/api/auth/users/:id', () =>
        HttpResponse.json({ username: ['此帳號已被使用'] }, { status: 400 }),
      ),
    )
    const { wrapper } = await mountSection()
    await wrapper.find('[data-test="profile-username"]').setValue('taken')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-test="profile-error"]').text()).toContain('此帳號已被使用')
  })
})
