import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import AppShell from '@/components/AppShell.vue'
import App from '@/App.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'

// 守衛邏輯在 router.spec 直測；這裡用無守衛的 fresh router 專測殼與路由表。
function freshRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes })
}

let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  localStorage.clear()
})

describe('佔位路由', () => {
  it.each(['/transactions', '/transactions/new', '/reports', '/settings', '/settings/goals'])(
    '%s 已註冊且 requiresAuth（守衛沿用 → 未登入導 /login）',
    (path) => {
      const resolved = freshRouter().resolve(path)
      expect(resolved.matched.length).toBeGreaterThan(0)
      expect(resolved.meta.requiresAuth).toBe(true)
    },
  )
})

describe('AppShell 導覽', () => {
  it('tabbar 四格＋FAB＋sidebar 更多六子項各指向對應路由', async () => {
    const router = freshRouter()
    await router.push('/')
    const wrapper = mount(AppShell, { global: { plugins: [pinia, router] } })
    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))
    const targets = [
      '/',
      '/transactions',
      '/reports',
      '/settings',
      '/transactions/new', // FAB（手機）＋右上「+」（桌面）
      '/settings/accounts',
      '/settings/categories',
      '/settings/tags',
      '/settings/rules',
      '/settings/goals',
      '/settings/profile',
    ]
    for (const target of targets) {
      expect(hrefs, `缺 ${target}`).toContain(target)
    }
  })

  it('FAB 圖示為 SVG（文字「+」置中吃字型 metrics，會偏移）', async () => {
    const router = freshRouter()
    await router.push('/')
    const wrapper = mount(AppShell, { global: { plugins: [pinia, router] } })
    const fabs = wrapper.findAll('a[aria-label="記一筆"]')
    expect(fabs).toHaveLength(2) // 桌面右上＋手機 tabbar 中央
    for (const fab of fabs) {
      expect(fab.find('svg').exists()).toBe(true)
      expect(fab.text().trim()).toBe('')
    }
  })

  it('sidebar 登出鈕：清 session 並導 /login', async () => {
    const auth = useAuthStore()
    auth.access = 'token'
    const router = freshRouter()
    await router.push('/')
    const wrapper = mount(AppShell, { global: { plugins: [pinia, router] } })
    await wrapper.find('[data-test="sidebar-logout"]').trigger('click')
    await flushPromises()
    expect(auth.access).toBeNull()
    // /login 是 lazy route：等動態載入完成，單一 flushPromises 不夠。
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/login'))
  })
})

describe('App 殼顯示邊界', () => {
  it('認證頁不顯示殼', async () => {
    const router = freshRouter()
    await router.push('/login')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.find('[data-test="tabbar"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="sidebar"]').exists()).toBe(false)
  })

  it('受保護頁顯示殼', async () => {
    useAuthStore().access = 'token'
    const router = freshRouter()
    await router.push('/')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(wrapper.find('[data-test="tabbar"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="sidebar"]').exists()).toBe(true)
  })
})
