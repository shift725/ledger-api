import type { components } from './schema'

// auth 四端點用原生 fetch，不走 client.ts 的 openapi-fetch client——理由是行為，
// 不是型別：client 的 middleware 會自動掛 Bearer、收到 401 就打 refresh 再重放，
// 而 refresh 正是 middleware 依賴的零件（若走 client，refresh 失敗的 401 會再觸發
// refresh、無限遞迴）；login/register 當下還沒有 token，401 意味帳密錯而非「該續期」，
// 必須原樣浮給呼叫端顯示。本檔也是 client → store → auth 這條 ESM import 鏈的
// 底層，不得回頭 import client。
//
// 型別一律來自凍結契約的 codegen（schema.d.ts）：契約 1.0.1 修正了 auth 回應
// （與 logout 請求）的形狀宣告，先前引註後端行號的手寫過渡型別已退場。

export type RegisterInput = components['schemas']['UserRegister']

export type LoginResponse = components['schemas']['LoginResponse']

export type RegisterResponse = components['schemas']['RegisterResponse']

/** rotation 開啟：除新 access 外，一併回傳新 refresh。 */
export type RefreshResponse = components['schemas']['TokenRefresh']

export type LogoutResponse = components['schemas']['LogoutResponse']

/** auth 端點的非 2xx 回應；body 帶解析後的錯誤 payload 供 UI 顯示。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`API error ${status}`)
    this.name = 'ApiError'
  }
}

async function postJson<T>(path: string, body: unknown, accessToken?: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) })
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return postJson('/api/auth/login/', { email, password })
}

export function register(input: RegisterInput): Promise<RegisterResponse> {
  return postJson('/api/auth/register/', input)
}

export function refresh(refreshToken: string): Promise<RefreshResponse> {
  return postJson('/api/auth/token/refresh/', { refresh: refreshToken })
}

export function logout(refreshToken: string, accessToken: string): Promise<LogoutResponse> {
  return postJson('/api/auth/logout/', { refresh: refreshToken }, accessToken)
}
