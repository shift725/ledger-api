import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import CategoryTab from '@/components/reports/CategoryTab.vue'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

// ChartCanvas stub 掉（happy-dom 無 canvas）；CategoryTab 不用 router，只需 active pinia
// 讓 api client 的 middleware 讀得到 access。
async function mountCategory() {
  setActivePinia(createPinia())
  useAuthStore().access = 'token'
  const wrapper = mount(CategoryTab, { global: { stubs: { ChartCanvas: true } } })
  await flushPromises()
  return wrapper
}

beforeEach(() => localStorage.clear())

describe('CategoryTab — 換月重抓、切收支不抓', () => {
  it('onMounted 一發；切收支 0 發（同資料換值）；換月 +1', async () => {
    const counter = { n: 0 }
    server.use(
      http.get('*/api/ledger/reports/summary/by-category/', () => {
        counter.n++
        return HttpResponse.json({
          year: 2026,
          month: 7,
          categories: [
            { category_id: 'c1', category_name: '餐飲', income: '0.00', expense: '800.00' },
          ],
        })
      }),
    )
    const wrapper = await mountCategory()
    expect(counter.n).toBe(1) // 進頁一發

    const incomeBtn = wrapper.findAll('button').find((b) => b.text() === '收入')
    await incomeBtn!.trigger('click')
    await flushPromises()
    expect(counter.n).toBe(1) // 切收支：同資料換值、不重抓

    // 換月：挑一個保證不同於當月的值（免依賴真實日期）
    const now = new Date()
    const otherMonth = now.getMonth() + 1 === 1 ? '2' : '1'
    await wrapper.find('[data-test="month-select"]').setValue(otherMonth)
    await flushPromises()
    expect(counter.n).toBe(2) // 換月重抓
  })
})
