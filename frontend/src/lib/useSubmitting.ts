import { ref } from 'vue'

/**
 * 送出鍵防連點：`run()` 執行期間 `submitting` 為 true，元件把它綁到按鈕的 `:disabled`。
 *
 * 解的問題：送出到回應之間有網路延遲，期間按鈕若仍可點，使用者看不到回饋就會再按一次，
 * 後端於是收到兩發請求——交易與轉帳沒有冪等鍵，那就是兩筆重複資料。
 *
 * 元件的接法是「既有 `submit()` 更名為 `doSubmit()`，再 `useSubmitting(doSubmit)`」，
 * 而不是把 try/finally 直接包進既有函式：每支送出函式內都有數個 early return
 * （驗證失敗、離線、後端 400），整段包進 try 需要重排全部縮排，diff 大且容易改壞既有邏輯。
 * 更名外包則業務邏輯一行不動，模板的 `@submit.prevent="submit"` 也不必改。
 *
 * `run()` 不吞例外：`doSubmit` 若拋錯，行為與接上本 composable 之前相同，
 * `finally` 只負責把鎖解開——少了它，一次意外的例外就會讓按鈕永久卡死。
 */
export function useSubmitting(fn: () => Promise<void>) {
  const submitting = ref(false)

  async function run() {
    // 入口守衛：讓「不重複送出」是 run() 自身的性質，而不是每個模板都記得綁對
    // :disabled 才成立的巧合（程式呼叫、鍵盤送出等繞過按鈕的路徑一併擋掉）。
    if (submitting.value) return
    submitting.value = true
    try {
      await fn()
    } finally {
      submitting.value = false
    }
  }

  return { submitting, run }
}
