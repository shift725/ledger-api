import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { http, HttpResponse } from 'msw'
import DashboardView from '@/views/DashboardView.vue'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { server } from '@/mocks/node'

async function mountDashboard(): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().access = 'token'
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/')
  const wrapper = mount(DashboardView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
})

describe('DashboardView 五區塊', () => {
  it('五區塊罐頭資料上屏', async () => {
    const wrapper = await mountDashboard()
    await vi.waitFor(() => expect(wrapper.text()).toContain('52,000'))

    // ① 本月摘要（標籤寫明範圍，與②「今日」對稱；淨額正值帶 +；全零小數部省略）
    expect(wrapper.text()).toContain('本月收入')
    expect(wrapper.text()).toContain('本月支出')
    expect(wrapper.text()).toContain('31,240')
    expect(wrapper.text()).toContain('本月淨額')
    expect(wrapper.text()).toContain('+20,760')
    // ② 今日
    expect(wrapper.text()).toContain('今日支出')
    expect(wrapper.text()).toContain('340')
    // ③ 帳戶餘額
    expect(wrapper.text()).toContain('總資產')
    expect(wrapper.text()).toContain('248,350')
    expect(wrapper.text()).toContain('現金')
    expect(wrapper.text()).toContain('台新銀行')
    // ④ 儲蓄目標（13600/20000=68%、98400/240000=41%）
    expect(wrapper.text()).toContain('68%')
    expect(wrapper.text()).toContain('41%')
    // ⑤ 最近交易：name fallback、自動徽章、查看全部
    expect(wrapper.text()).toContain('午餐')
    expect(wrapper.text()).toContain('薪水') // name 空 → category_name
    expect(wrapper.text()).toContain('未命名') // name 與 category 皆空
    expect(wrapper.text()).toContain('自動') // source_rule 非 null
    const allLink = wrapper.findAll('a').find((a) => a.text().includes('查看全部'))
    expect(allLink?.attributes('href')).toBe('/transactions')
  })

  it('零值不著語意色：今日收入 0 → muted、無 income 色', async () => {
    const wrapper = await mountDashboard()
    await vi.waitFor(() => expect(wrapper.find('[data-test="today-income"]').exists()).toBe(true))
    const amount = wrapper.find('[data-test="today-income"]')
    expect(amount.text()).toBe('0')
    expect(amount.classes()).toContain('text-ink-2')
    expect(amount.classes()).not.toContain('text-income')
  })

  it('goal 為 null → 引導文案連 /settings/goals', async () => {
    server.use(
      http.get('*/api/ledger/reports/savings-goal-status/', ({ request }) => {
        const month = new URL(request.url).searchParams.get('month')
        return HttpResponse.json({
          period_type: month ? 'monthly' : 'yearly',
          year: 2026,
          month: month ? Number(month) : null,
          goal_amount: null,
          actual_net: '13600.00',
          difference: null,
          achieved: null,
        })
      }),
    )
    const wrapper = await mountDashboard()
    await vi.waitFor(() => {
      const guide = wrapper.findAll('a').filter((a) => a.attributes('href') === '/settings/goals')
      expect(guide.length).toBeGreaterThan(0)
    })
    expect(wrapper.text()).toContain('尚未設定')
  })

  it('區塊級降級：summary 500 → 該區塊錯誤態、其餘照常', async () => {
    server.use(
      http.get('*/api/ledger/reports/summary/', () => new HttpResponse(null, { status: 500 })),
    )
    const wrapper = await mountDashboard()
    await vi.waitFor(() =>
      expect(wrapper.find('[data-test="block-summary"]').text()).toContain('載入失敗'),
    )
    await vi.waitFor(() =>
      expect(wrapper.find('[data-test="block-balance"]').text()).toContain('248,350'),
    )
    expect(wrapper.find('[data-test="block-recent"]').text()).toContain('午餐')
  })

  it('色點接線：帳戶與交易分類各自 scope 依出現序取色；category null 不顯示色點', async () => {
    const wrapper = await mountDashboard()
    await vi.waitFor(() => expect(wrapper.text()).toContain('現金'))
    const accountDots = wrapper.findAll('[data-test="block-balance"] [data-test="dot"]')
    expect(accountDots.length).toBe(2)
    expect(accountDots[0]?.attributes('style')).toContain('--dot-1')
    expect(accountDots[1]?.attributes('style')).toContain('--dot-2')
    // 交易 4 筆、3 筆有 category（各自首現序 1/2/3），t4 無 category → 無點
    const txnDots = wrapper.findAll('[data-test="block-recent"] [data-test="dot"]')
    expect(txnDots.length).toBe(3)
    expect(txnDots[0]?.attributes('style')).toContain('--dot-1')
  })
})
