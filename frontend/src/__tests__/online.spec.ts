import { afterEach, describe, expect, it } from 'vitest'
import { isOnline } from '@/lib/online'

describe('online — 離線狀態源', () => {
  afterEach(() => {
    // 復原為在線，避免殘留影響同檔後續測試
    window.dispatchEvent(new Event('online'))
  })

  it('初值跟隨 navigator.onLine（happy-dom 預設在線）', () => {
    expect(isOnline.value).toBe(true)
  })

  it('offline 事件 → false；online 事件 → true', () => {
    window.dispatchEvent(new Event('offline'))
    expect(isOnline.value).toBe(false)

    window.dispatchEvent(new Event('online'))
    expect(isOnline.value).toBe(true)
  })
})
