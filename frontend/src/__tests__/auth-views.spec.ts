import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/node'
import { routes } from '@/router'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'
import SettingsView from '@/views/SettingsView.vue'
import { useAuthStore } from '@/stores/auth'

// Guard-free router (the guard lives on the app singleton). Memory history has
// no initial URL, so the router must be pushed to a start location before use —
// without it, isReady()/navigation never resolves. push() awaits readiness.
async function routerAt(location: string) {
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(location)
  return router
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})
afterEach(() => vi.restoreAllMocks())

describe('LoginView', () => {
  it('logs in and redirects to the saved destination', async () => {
    const router = await routerAt('/login?redirect=/reports')
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined)

    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    await wrapper.find('input[type=email]').setValue('demo@example.com')
    await wrapper.find('input[type=password]').setValue('pw')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(useAuthStore().isAuthenticated).toBe(true)
    expect(push).toHaveBeenCalledWith('/reports')
  })

  it('shows an error and stays logged out on bad credentials', async () => {
    server.use(
      http.post('*/api/auth/login/', () => HttpResponse.json({ detail: 'no' }, { status: 401 })),
    )
    const router = await routerAt('/login')
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined)

    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    await wrapper.find('input[type=email]').setValue('demo@example.com')
    await wrapper.find('input[type=password]').setValue('bad')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(push).not.toHaveBeenCalled()
    expect(wrapper.find('[role=alert]').exists()).toBe(true)
    expect(useAuthStore().isAuthenticated).toBe(false)
  })
})

describe('RegisterView', () => {
  it('registers and lands authenticated on the home route', async () => {
    const router = await routerAt('/register')
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined)

    const wrapper = mount(RegisterView, { global: { plugins: [router] } })
    await wrapper.find('input[autocomplete=username]').setValue('newbie')
    await wrapper.find('input[type=email]').setValue('new@example.com')
    await wrapper.findAll('input[type=password]')[0]?.setValue('pw123456')
    await wrapper.findAll('input[type=password]')[1]?.setValue('pw123456')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(useAuthStore().isAuthenticated).toBe(true)
    expect(push).toHaveBeenCalledWith('/')
  })

  it('surfaces the backend message on a duplicate account (409)', async () => {
    server.use(
      http.post('*/api/auth/register/', () =>
        HttpResponse.json({ error: '帳號或 email 已被使用' }, { status: 409 }),
      ),
    )
    const router = await routerAt('/register')

    const wrapper = mount(RegisterView, { global: { plugins: [router] } })
    await wrapper.find('input[autocomplete=username]').setValue('dup')
    await wrapper.find('input[type=email]').setValue('dup@example.com')
    await wrapper.findAll('input[type=password]')[0]?.setValue('pw123456')
    await wrapper.findAll('input[type=password]')[1]?.setValue('pw123456')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role=alert]').text()).toContain('已被使用')
    expect(useAuthStore().isAuthenticated).toBe(false)
  })
})

describe('SettingsView（登出入口，自佔位總覽移入）', () => {
  it('shows the username and logs out to /login', async () => {
    const store = useAuthStore()
    await store.login('demo@example.com', 'pw')
    const router = await routerAt('/settings')
    const push = vi.spyOn(router, 'push').mockResolvedValue(undefined)

    const wrapper = mount(SettingsView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('demo')

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(store.isAuthenticated).toBe(false)
    expect(push).toHaveBeenCalledWith('/login')
  })
})
