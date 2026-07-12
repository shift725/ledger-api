import type { components } from './schema'

// Auth endpoints use plain fetch, not the typed openapi-fetch client, because
// three of the four responses (and logout's request) don't match the frozen
// openapi.yaml: drf-spectacular typed each from the serializer used for *input*,
// so the codegen response types are wrong. Same root cause as the known
// "LogoutView has no typed request body" limitation in the frozen schema.
// The seam types below are hand-written with their backend source cited; delete
// them and switch to codegen once the upstream annotations are fixed.
//
// Requests that ARE correctly typed by the schema reuse the codegen types.

export type RegisterInput = components['schemas']['UserRegister']

/** login 200 — accounts/serializers.py:72-84 (user is a hand-built subset, not UserSerializer). */
export interface LoginResponse {
  access: string
  refresh: string
  user: { id: string; username: string; email: string; role: string }
}

/** register 201 — accounts/views.py:39-50 (user IS the full UserSerializer). */
export interface RegisterResponse {
  message: string
  user: components['schemas']['User']
  tokens: { access: string; refresh: string }
}

/** refresh 200 — schema-correct; rotation returns a new refresh alongside access. */
export type RefreshResponse = components['schemas']['TokenRefresh']

/** Non-2xx from an auth endpoint. `body` carries the parsed error payload for the UI. */
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

export function logout(refreshToken: string, accessToken: string): Promise<{ message: string }> {
  return postJson('/api/auth/logout/', { refresh: refreshToken }, accessToken)
}
