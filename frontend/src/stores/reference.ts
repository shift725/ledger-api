import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/client'
import type { components } from '@/api/schema'

// 帳戶/分類/標籤三份小清單：表單與過濾面板共用的參照資料。
// 策略＝SWR：首次 ensure() 冷啟 await 抓齊；之後 ensure() 立即回快取＋背景重抓。
// 三份一起管（兩處消費者都同時要三份），single-flight 防並發重抓。
type Account = components['schemas']['Account']
type Category = components['schemas']['Category']
type Tag = components['schemas']['Tag']

interface Page<T> {
  results: T[]
  next?: string | null
}

// 翻頁抓齊：next 非 null 就續抓下一頁（不解析 next URL，改遞增 page，避免耦合後端 host）。
async function fetchAll<T>(
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

  let inFlight: Promise<void> | null = null

  function refresh(): Promise<void> {
    if (inFlight) return inFlight
    inFlight = Promise.all([
      fetchAll<Account>((page) =>
        api.GET('/api/ledger/accounts/', { params: { query: { page } } }),
      ),
      fetchAll<Category>((page) =>
        api.GET('/api/ledger/categories/', { params: { query: { page } } }),
      ),
      fetchAll<Tag>((page) => api.GET('/api/ledger/tags/', { params: { query: { page } } })),
    ])
      .then(([a, c, t]) => {
        accounts.value = a
        categories.value = c
        tags.value = t
        loaded.value = true
      })
      .finally(() => {
        inFlight = null
      })
    return inFlight
  }

  // 暖啟走 SWR：立即回快取、背景刷新（不 await）；冷啟 await 抓齊。
  function ensure(): Promise<void> {
    if (loaded.value) {
      void refresh()
      return Promise.resolve()
    }
    return refresh()
  }

  return { accounts, categories, tags, loaded, ensure, refresh }
})
