import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { routes } from '@/router'
import SettingsView from '@/views/SettingsView.vue'
import SettingsSectionView from '@/views/SettingsSectionView.vue'
import { SETTINGS_SECTIONS } from '@/lib/settingsSections'

function freshRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
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
  it.each(SETTINGS_SECTIONS.map((s) => [s.slug, s.label]))(
    '合法 section「%s」顯示標題「%s」',
    async (slug, label) => {
      const router = freshRouter()
      await router.push(`/settings/${slug}`)
      const wrapper = mount(SettingsSectionView, { global: { plugins: [router] } })
      expect(wrapper.text()).toContain(label)
      expect(wrapper.find(`[data-test="section-${slug}"]`).exists()).toBe(true)
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
