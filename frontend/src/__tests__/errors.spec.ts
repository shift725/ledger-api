import { describe, expect, it } from 'vitest'
import { messagesFrom } from '@/lib/errors'

describe('messagesFrom', () => {
  it('攤平 DRF 逐欄陣列、以「；」串接', () => {
    expect(messagesFrom({ name: ['此名稱已使用'], amount: ['必須大於 0'] })).toBe(
      '此名稱已使用；必須大於 0',
    )
  })

  it('取字串型錯誤（如 409 的 detail）', () => {
    expect(messagesFrom({ detail: '帳戶尚有交易或定期定額規則，無法刪除' })).toBe(
      '帳戶尚有交易或定期定額規則，無法刪除',
    )
  })

  it('非物件或空錯誤 → 泛用文案', () => {
    expect(messagesFrom(null)).toBe('操作失敗，請稍後再試')
    expect(messagesFrom('boom')).toBe('操作失敗，請稍後再試')
    expect(messagesFrom({})).toBe('操作失敗，請稍後再試')
  })
})
