import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { http, HttpResponse } from 'msw'
import RangeTab from '@/components/reports/RangeTab.vue'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

async function mountRange() {
  setActivePinia(createPinia())
  useAuthStore().access = 'token'
  const wrapper = mount(RangeTab)
  await flushPromises()
  return wrapper
}

beforeEach(() => localStorage.clear())

describe('RangeTab — 自訂區間', () => {
  it('start>end：前端擋送出、0 請求、顯示提示', async () => {
    const counter = { n: 0 }
    server.use(
      http.get('*/api/ledger/reports/summary/range/', () => {
        counter.n++
        return HttpResponse.json({ start: '', end: '', income: '0', expense: '0', net: '0' })
      }),
    )
    const wrapper = await mountRange()
    await wrapper.find('[data-test="range-start"]').setValue('2026-07-10')
    await wrapper.find('[data-test="range-end"]').setValue('2026-07-01')
    await wrapper.find('[data-test="range-submit"]').trigger('click')
    await flushPromises()

    expect(counter.n).toBe(0) // 前端擋下，未送
    expect(wrapper.text()).toContain('起日不可晚於迄日')
  })

  it('合法區間 → 出摘要三值（收入/支出/淨額）', async () => {
    server.use(
      http.get('*/api/ledger/reports/summary/range/', () =>
        HttpResponse.json({
          start: '2026-07-01',
          end: '2026-07-10',
          income: '5000.00',
          expense: '1234.00',
          net: '3766.00',
        }),
      ),
    )
    const wrapper = await mountRange()
    await wrapper.find('[data-test="range-start"]').setValue('2026-07-01')
    await wrapper.find('[data-test="range-end"]').setValue('2026-07-10')
    await wrapper.find('[data-test="range-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('5,000')
    expect(wrapper.text()).toContain('1,234')
    expect(wrapper.text()).toContain('+3,766') // 淨額帶正號
  })
})
