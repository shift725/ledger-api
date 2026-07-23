import { describe, expect, it } from 'vitest'
import { useSubmitting } from '@/lib/useSubmitting'

describe('useSubmitting', () => {
  it('執行期間鎖住：請求還在飛，再送一次不會重複執行', async () => {
    let calls = 0
    let release!: () => void
    const inFlight = new Promise<void>((resolve) => (release = resolve))
    const { submitting, run } = useSubmitting(async () => {
      calls += 1
      await inFlight
    })

    const first = run()
    expect(submitting.value).toBe(true)

    await run() // 連點第二下
    expect(calls).toBe(1)

    release()
    await first
    expect(submitting.value).toBe(false)
    expect(calls).toBe(1)
  })

  it('內層拋錯也要解鎖，否則按鈕永久卡死、使用者再也存不了', async () => {
    let calls = 0
    const { submitting, run } = useSubmitting(async () => {
      calls += 1
      throw new Error('boom')
    })

    await expect(run()).rejects.toThrow('boom')
    expect(submitting.value).toBe(false)

    await expect(run()).rejects.toThrow('boom')
    expect(calls).toBe(2)
  })
})
