import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { http, HttpResponse } from 'msw'
import ReportsView from '@/views/ReportsView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

// ChartCanvas 在 happy-dom 無 canvas 2d context（new Chart 會炸）→ stub 掉：測的是
// 抓取節制與資料流，不測 Chart.js 本體（圖靠真後端手測）。
async function mountReports(location: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(location)
  const wrapper = mount(ReportsView, {
    global: { plugins: [pinia, router], stubs: { ChartCanvas: true } },
  })
  await flushPromises()
  return { wrapper, router }
}

async function clickTab(wrapper: VueWrapper, label: string) {
  const btn = wrapper.findAll('[role="tab"]').find((b) => b.text() === label)
  await btn!.trigger('click')
  await flushPromises()
}

beforeEach(() => localStorage.clear())

describe('報表 balance-history 節制取用', () => {
  it('進頁抓一次；切走再切回不重抓（KeepAlive）；重整鈕 +1', async () => {
    const counter = { n: 0 }
    server.use(
      http.get('*/api/ledger/reports/balance-history/', () => {
        counter.n++
        return HttpResponse.json([
          { account_id: 'a', account_name: 'A', months: [{ month: '2026-07', balance: '100.00' }] },
        ])
      }),
    )

    const { wrapper } = await mountReports('/reports') // 預設 balance tab
    expect(counter.n).toBe(1) // 進頁一發
    expect(wrapper.text()).toContain('各帳戶目前餘額') // 精確表渲染
    expect(wrapper.text()).toContain('100') // A 帳戶餘額（formatAmount 後、全零小數部省略）

    await clickTab(wrapper, '標籤')
    expect(counter.n).toBe(1) // 切走不抓

    await clickTab(wrapper, '餘額走勢')
    expect(counter.n).toBe(1) // 切回不重抓

    await wrapper.find('[data-test="refresh-balance"]').trigger('click')
    await flushPromises()
    expect(counter.n).toBe(2) // 重整 +1
  })

  it('查無資料 → 空態文案', async () => {
    server.use(http.get('*/api/ledger/reports/balance-history/', () => HttpResponse.json([])))
    const { wrapper } = await mountReports('/reports')
    expect(wrapper.text()).toContain('尚無餘額資料')
  })
})
