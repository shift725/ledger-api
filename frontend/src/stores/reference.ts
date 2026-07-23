import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { components } from '@/api/schema'

// 帳戶/分類/標籤三份小清單：表單與過濾面板共用的參照資料。
// 策略＝SWR：首次 ensure() 冷啟 await 抓齊；之後 ensure() 立即回快取＋背景重抓。
// 三份一起管（兩處消費者都同時要三份），single-flight 防並發重抓。
//
// 持久層＝localStorage、key 帶 user id（`ref:{userId}`）：離線也開得了表單與過濾面板；
// 同機換帳號天然隔離——快取層刻意放 app 層而非 service worker，SW 的 HTTP cache
// 不看 Authorization header，放那邊會讀到前帳號的資料。
type Account = components['schemas']['Account']
type Category = components['schemas']['Category']
type Tag = components['schemas']['Tag']

interface Page<T> {
  results: T[]
  next?: string | null
}

// 翻頁抓齊：next 非 null 就續抓下一頁（不解析 next URL，改遞增 page，避免耦合後端 host）。
// export 供設定面的 rules/goals 區塊在自己的 store 外復用同一套翻頁邏輯。
export async function fetchAll<T>(
  fetchPage: (page: number) => Promise<{ data?: Page<T>; error?: unknown }>,
): Promise<T[]> {
  const items: T[] = []
  let page = 1
  for (;;) {
    const { data, error } = await fetchPage(page)
    if (error !== undefined || data === undefined) throw error ?? new Error('empty response')
    items.push(...data.results)
    if (!data.next) break
    page += 1
  }
  return items
}

export const useReferenceStore = defineStore('reference', () => {
  const accounts = ref<Account[]>([])
  const categories = ref<Category[]>([])
  const tags = ref<Tag[]>([])
  const loaded = ref(false)

  // 記憶體資料屬於哪個 user——換帳號時據此重置，前帳號資料不殘留給下一位。
  let ownerId: string | null = null
  let inFlight: Promise<void> | null = null
  // 抓取的世代序號：判斷回來的這批還是不是最新的一輪（與 ownerId 同性質，一個判歸屬、一個判新舊）。
  let generation = 0

  function cacheKey(): string | null {
    const user = useAuthStore().user
    return user ? `ref:${user.id}` : null
  }

  // localStorage 讀寫都 try/catch 吞錯（quota 滿、隱私模式）：快取失敗不阻塞網路路徑。
  function hydrate(): boolean {
    const key = cacheKey()
    if (!key) return false
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return false
      const cached = JSON.parse(raw)
      accounts.value = cached.accounts
      categories.value = cached.categories
      tags.value = cached.tags
      return true
    } catch {
      return false
    }
  }

  function persist() {
    const key = cacheKey()
    if (!key) return
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          accounts: accounts.value,
          categories: categories.value,
          tags: tags.value,
        }),
      )
    } catch {
      /* 快取寫不進去就算了 */
    }
  }

  // 一律抓新的，不共用在途請求：refresh() 的呼叫者全是「剛寫完資料」，共用到的那發
  // 是寫入前發出的，回來的清單看不到新資源，畫面就停在舊狀態。掛載尖峰的去重責任在
  // ensure()——它才是同時被多個元件呼叫的那個。
  function refresh(): Promise<void> {
    const forOwner = ownerId
    const mine = ++generation
    const run = Promise.all([
      fetchAll<Account>((page) =>
        api.GET('/api/ledger/accounts/', { params: { query: { page } } }),
      ),
      fetchAll<Category>((page) =>
        api.GET('/api/ledger/categories/', { params: { query: { page } } }),
      ),
      fetchAll<Tag>((page) => api.GET('/api/ledger/tags/', { params: { query: { page } } })),
    ])
      .then(([a, c, t]) => {
        // 抓取途中換了帳號：這批結果屬於前一位，丟棄（別把 A 的資料寫進 B 的畫面）。
        if (forOwner !== ownerId) return
        // 已經有更新的抓取接手：這批是過期的，丟棄。少了這道看守，上面「一律抓新的」
        // 等於白做——先發出的那輪若晚回（正是慢網路下會發生的事），它的舊清單會蓋掉
        // 新抓回來的資料，寫入的資源一樣不會出現。
        if (mine !== generation) return
        accounts.value = a
        categories.value = c
        tags.value = t
        loaded.value = true
        persist()
      })
      .finally(() => {
        if (mine === generation) inFlight = null
      })
    inFlight = run
    return run
  }

  // 暖啟走 SWR：立即回快取、背景刷新（不 await、失敗靜默——離線時本來就會失敗）；
  // 冷啟先試 localStorage（離線也開得起來），沒有才 await 網路。
  function ensure(): Promise<void> {
    const uid = useAuthStore().user?.id ?? null
    if (ownerId !== uid) {
      ownerId = uid
      loaded.value = false
      accounts.value = []
      categories.value = []
      tags.value = []
      inFlight = null // 前一位的在途請求作廢（結果會被上面的 owner 檢查丟棄）
      if (hydrate()) loaded.value = true
    }
    // 去重住在這裡：同一頁多個元件掛載會各喊一次 ensure()，共用同一發即可，
    // 它們要的只是「有資料可用」，不像寫入後的 refresh() 需要呼叫當下之後的資料。
    if (loaded.value) {
      void (inFlight ?? refresh()).catch(() => {})
      return Promise.resolve()
    }
    return inFlight ?? refresh()
  }

  return { accounts, categories, tags, loaded, ensure, refresh }
})
