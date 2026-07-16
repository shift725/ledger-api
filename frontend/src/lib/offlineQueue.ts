import { readonly, ref } from 'vue'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useReferenceStore } from '@/stores/reference'
import { toast } from '@/lib/toast'
import type { components } from '@/api/schema'

// 離線記帳佇列：離線（或網路失敗）時送不出去的交易先存 localStorage，
// 恢復連線／App 啟動時重放。key 帶 user id——同機換帳號互不可見。
//
// 刻意簡單（衝突解決 out of scope）：出隊即視為已送；「POST 成功但回應沒收到」
// 的極端窗口會留下重複一筆（手動交易無冪等鍵，正解是契約加冪等鍵——backlog）。
type Transaction = components['schemas']['Transaction']

// 契約無獨立寫入 schema：剝掉唯讀衍生欄的寫入形狀（表單與佇列共用這份定義）。
export type TxnWrite = Omit<
  Transaction,
  'id' | 'source_rule' | 'account_name' | 'category_name' | 'tag_names'
>

interface QueuedItem {
  id: string // 佇列項自身的識別（出隊用），與後端無關
  txn: TxnWrite
}

const count = ref(0)
export const queueCount = readonly(count) // 離線 banner 的「N 筆待送」

function key(): string | null {
  const user = useAuthStore().user
  return user ? `queue:${user.id}` : null
}

// localStorage 讀寫 try/catch 吞錯（quota、隱私模式）：佇列壞了不炸 App。
function read(): QueuedItem[] {
  const k = key()
  if (!k) return []
  try {
    return JSON.parse(localStorage.getItem(k) ?? '[]')
  } catch {
    return []
  }
}

function write(items: QueuedItem[]) {
  const k = key()
  if (!k) return
  try {
    localStorage.setItem(k, JSON.stringify(items))
  } catch {
    /* 寫不進去就只活在記憶體，重整會掉——比阻塞記帳好 */
  }
  count.value = items.length
}

export function enqueue(txn: TxnWrite) {
  const k = key()
  if (!k) return
  write([...read(), { id: crypto.randomUUID(), txn }])
}

// 離線冷啟不會跑 replay（沒網路），banner 的筆數要另行從 localStorage 對齊。
export function syncCount() {
  count.value = read().length
}

// single-flight：online 事件與啟動可能同時觸發，共用同一輪重放。
let replaying: Promise<void> | null = null
export function replay(): Promise<void> {
  if (replaying) return replaying
  replaying = doReplay().finally(() => {
    replaying = null
  })
  return replaying
}

async function doReplay(): Promise<void> {
  count.value = read().length
  const items = read()
  if (!items.length) return

  let sent = 0
  let dropped = 0
  for (const item of items) {
    let res
    try {
      // 契約以同一 Transaction 型別描述 body（含 readonly 衍生欄）→ 單點轉型，同表單。
      res = await api.POST('/api/ledger/transactions/', {
        body: item.txn as unknown as Transaction,
      })
    } catch {
      break // 網路還是不通：整批留隊，下次再試
    }
    // status 在 narrow 前取（兩個 union 成員共有）；契約 error 型別為 never，
    // 以 res.error 做 truthy narrow 會讓型別 collapse，改以 data 有無判成敗。
    const status = res.response.status
    if (res.data === undefined) {
      if (status === 401 || status >= 500) break // auth 死／伺服器暫時壞：留隊、別連發
      dropped++ // 其他 4xx＝資料已失效（如帳戶被刪）：出隊，毒丸不准卡佇列
    } else {
      sent++
    }
    write(read().filter((q) => q.id !== item.id))
  }

  if (sent || dropped) {
    const parts = []
    if (sent) parts.push(`已補送 ${sent} 筆離線交易`)
    if (dropped) parts.push(`${dropped} 筆已失效，無法補送`)
    toast(parts.join('；'))
  }
  if (sent) {
    // 補送改變了餘額：立刻背景刷新 reference（失敗靜默），
    // 消除「SWR 刷新先完成、不含補送筆」的短暫不一致窗口。
    void useReferenceStore()
      .refresh()
      .catch(() => {})
  }
}
