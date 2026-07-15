import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/lib/toast'
import router from '@/router'

// 業務端點的 typed client。auth 四端點繞過本 client、在 api/auth.ts 用原生
// fetch——理由見該檔檔頭（refresh 是本 middleware 依賴的零件，走回來會遞迴；
// auth 端點的 401 語意也不同，不該觸發自動續期）。
//
// 本模組 import 了 store 與 router，但兩者只在下面的 callback 內呼叫（絕不在
// 模組頂層），client → store → api/auth 與 client → router → store 這兩條
// ESM import 環才安全。任一呼叫移到頂層＝在模組初始化半途執行，會直接炸。

// request body 是一次性 stream：fetch 會消耗它，吃到 401 的請求無法原樣重送。
// 所以每個請求送出前先 clone 留底，refresh 完重放 clone（body 完好）。以
// openapi-fetch 的 per-request id 為鍵，把 onRequest 與 onResponse 串起來。
const replayClones = new Map<string, Request>()

const authMiddleware: Middleware = {
  onRequest({ request, id }) {
    const { access } = useAuthStore()
    if (access) request.headers.set('Authorization', `Bearer ${access}`)
    replayClones.set(id, request.clone())
    return request
  },

  async onResponse({ response, id }) {
    const retry = replayClones.get(id)
    replayClones.delete(id)

    // 429：全域統一提示，讀 Retry-After 給可重試時間（DRF 回整數秒）。只提示、不吞
    // 回應——呼叫端的錯誤態照舊、避免白屏。
    if (response.status === 429) {
      const secs = Number(response.headers.get('Retry-After'))
      const when = Number.isFinite(secs) && secs > 0 ? `${secs} 秒後` : '稍後'
      toast(`請求過於頻繁，請${when}再試`)
      return response
    }

    if (response.status !== 401 || !retry) return response

    const store = useAuthStore()
    let access: string
    try {
      access = await store.refreshAccess()
    } catch {
      // refresh token 已死（過期或進黑名單）：session 到此結束。
      store.clearSession()
      await router.push('/login')
      return response
    }

    retry.headers.set('Authorization', `Bearer ${access}`)
    return fetch(retry)
  },
}

export const api = createClient<paths>()
api.use(authMiddleware)
