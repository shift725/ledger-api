import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { http, HttpResponse } from 'msw'
import { routes, authGuard } from '@/router'
import SettingsView from '@/views/SettingsView.vue'
import SettingsSectionView from '@/views/SettingsSectionView.vue'
import { SETTINGS_SECTIONS } from '@/lib/settingsSections'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

function freshRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('SettingsView 離線登出（整合：真守衛＋lazy 路由）', () => {
  it('confirm 確定 → 一次導到 /login', async () => {
    const auth = useAuthStore()
    auth.user = { id: 'user-a', username: 'a', email: 'a@x.tw', role: 'member' }
    auth.access = 't'
    auth.refresh = 'r'
    server.use(http.post('*/api/auth/logout/', () => HttpResponse.error()))

    const router = freshRouter()
    router.beforeEach(authGuard) // 掛真守衛，走與生產同一條導航鏈
    await router.push('/settings')
    const wrapper = mount(SettingsView, { global: { plugins: [router] } })

    window.dispatchEvent(new Event('offline'))
    vi.stubGlobal(
      'confirm',
      vi.fn<() => boolean>(() => true),
    )
    try {
      await wrapper.find('[data-test="logout"]').trigger('click')
      await flushPromises()
      await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/login'))
    } finally {
      vi.unstubAllGlobals()
      window.dispatchEvent(new Event('online'))
    }
  })
})

describe('SettingsView 清單', () => {
  it('列出六個設定子頁連結＋登出鈕', async () => {
    const router = freshRouter()
    await router.push('/settings')
    const wrapper = mount(SettingsView, { global: { plugins: [router] } })
    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))
    for (const s of SETTINGS_SECTIONS) {
      expect(hrefs, `缺 /settings/${s.slug}`).toContain(`/settings/${s.slug}`)
    }
    expect(wrapper.find('[data-test="logout"]').exists()).toBe(true)
  })
})

describe('SettingsSectionView 派發', () => {
  // 派發契約＝合法 slug 掛出對應標題；區塊本體（真元件或佔位）各自於資源 spec 驗。
  it.each(SETTINGS_SECTIONS.map((s) => [s.slug, s.label]))(
    '合法 section「%s」顯示標題「%s」',
    async (slug, label) => {
      const router = freshRouter()
      await router.push(`/settings/${slug}`)
      const wrapper = mount(SettingsSectionView, { global: { plugins: [router] } })
      await flushPromises()
      expect(wrapper.text()).toContain(label)
    },
  )

  it('未知 section → 找不到此頁', async () => {
    const router = freshRouter()
    await router.push('/settings/nope')
    const wrapper = mount(SettingsSectionView, { global: { plugins: [router] } })
    expect(wrapper.find('[data-test="section-not-found"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('找不到此頁')
  })
})
