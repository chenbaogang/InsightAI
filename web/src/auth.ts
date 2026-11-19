/* 登录态与统一请求头：token 存 localStorage，401 由 App 层回调处理（回登录页）。 */

export interface Who {
  username: string
  display_name: string
  admin: boolean
  dept_code: string | null
  dept_name: string | null
  data_values: string[]
}

const TOKEN_KEY = 'insightai_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(t: string) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  const t = getToken()
  if (t) h['Authorization'] = `Bearer ${t}`
  return h
}

let onUnauthorized: (() => void) | null = null

/** App 注册：任意接口返回 401（token 过期/注销）就清掉登录态回到登录页 */
export function setUnauthorizedHandler(cb: () => void) {
  onUnauthorized = cb
}

export function handleUnauthorized(status: number) {
  if (status === 401) {
    setToken('')
    onUnauthorized?.()
  }
}

export function errText(body: any, status: number): string {
  const d = body?.detail
  if (typeof d === 'string' && d) return d
  if (Array.isArray(d)) {
    const parts = d
      .map((e: any) => {
        const field = Array.isArray(e?.loc) ? String(e.loc[e.loc.length - 1] ?? '') : ''
        const msg = String(e?.msg ?? '')
        return field ? `${field}：${msg}` : msg
      })
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  return `HTTP ${status}`
}

export async function login(username: string, password: string): Promise<{ token: string; user: Who }> {
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const d = await r.json()
  if (!r.ok) throw new Error(errText(d, r.status))
  setToken(d.token)
  return d
}

export async function logout() {
  const t = getToken()
  if (t) await fetch('/api/auth/logout', { method: 'POST', headers: authHeaders() }).catch(() => {})
  setToken('')
}

export async function fetchMe(): Promise<Who | null> {
  if (!getToken()) return null
  const r = await fetch('/api/auth/me', { headers: authHeaders() })
  if (!r.ok) {
    setToken('')
    return null
  }
  return r.json()
}