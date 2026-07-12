import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { toast, toastMessage } from '@/lib/toast'
import { toDatetimeLocal } from '@/lib/format'
import AppShell from '@/components/AppShell.vue'
import { routes } from '@/router'

afterEach(() => {
  toastMessage.value = '' // module-level ref，跨測試手動清
})

describe('toast（極簡全域提示）', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('toast(msg) 設訊息，逾時自動清空', () => {
    toast('已儲存', 2500)
    expect(toastMessage.value).toBe('已儲存')
    vi.advanceTimersByTime(2500)
    expect(toastMessage.value).toBe('')
  })

  it('連續 toast 重置計時器（後者蓋前者、不被前者的舊逾時清掉）', () => {
    toast('A', 2500)
    vi.advanceTimersByTime(1000)
    toast('B', 2500)
    expect(toastMessage.value).toBe('B')
    vi.advanceTimersByTime(2000) // A 原逾時點已過，但 B 重置了計時器
    expect(toastMessage.value).toBe('B')
    vi.advanceTimersByTime(500)
    expect(toastMessage.value).toBe('')
  })
})

describe('toDatetimeLocal（Date → datetime-local 值）', () => {
  it('回 YYYY-MM-DDTHH:mm（當地、補零、無秒）', () => {
    expect(toDatetimeLocal(new Date(2026, 6, 5, 9, 3))).toBe('2026-07-05T09:03')
    expect(toDatetimeLocal(new Date(2026, 11, 25, 23, 59))).toBe('2026-12-25T23:59')
  })
})

describe('AppShell 顯示 toast', () => {
  it('toastMessage 非空 → 顯示；空 → 不顯示', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/')
    const wrapper = mount(AppShell, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.find('[data-test="toast"]').exists()).toBe(false)
    toast('已儲存')
    await nextTick()
    const el = wrapper.find('[data-test="toast"]')
    expect(el.exists()).toBe(true)
    expect(el.text()).toBe('已儲存')
  })
})
