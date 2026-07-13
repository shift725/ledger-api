import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import ReportsView from '@/views/ReportsView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'

async function mountReports(location: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(location)
  const wrapper = mount(ReportsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, router }
}

function activeTabLabel(wrapper: VueWrapper): string | undefined {
  return wrapper
    .findAll('[role="tab"]')
    .find((b) => b.attributes('aria-selected') === 'true')
    ?.text()
}

beforeEach(() => localStorage.clear())

describe('ReportsView — tab 與 ?tab= 同步', () => {
  it('無 tab query → 預設餘額走勢', async () => {
    const { wrapper } = await mountReports('/reports')
    expect(activeTabLabel(wrapper)).toBe('餘額走勢')
  })

  it('?tab=tags 直開 → 落標籤 tab（可定址）', async () => {
    const { wrapper } = await mountReports('/reports?tab=tags')
    expect(activeTabLabel(wrapper)).toBe('標籤')
  })

  it('無效 tab 值 → 回退餘額走勢', async () => {
    const { wrapper } = await mountReports('/reports?tab=bogus')
    expect(activeTabLabel(wrapper)).toBe('餘額走勢')
  })

  it('點 tab → query 更新且用 replace（不堆歷史）', async () => {
    const { wrapper, router } = await mountReports('/reports')
    const replaceSpy = vi.spyOn(router, 'replace')
    const pushSpy = vi.spyOn(router, 'push')

    const tagBtn = wrapper.findAll('[role="tab"]').find((b) => b.text() === '標籤')
    await tagBtn!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.tab).toBe('tags')
    expect(replaceSpy).toHaveBeenCalledOnce()
    expect(pushSpy).not.toHaveBeenCalled()
  })
})
