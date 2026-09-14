import { normalizeApiUrl } from './api-url'
import { createApiError, readApiError } from './api-error'

const defaultDevUrl = typeof window !== 'undefined' && window.location.origin
  ? window.location.origin
  : 'http://localhost:8000'

const rawApiUrl = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? defaultDevUrl : '')
const pageOrigin = typeof window === 'undefined' ? '' : window.location.origin



let BASE = ''
let configurationError = null
try {
  BASE = normalizeApiUrl(rawApiUrl, { production: import.meta.env.PROD, pageOrigin })
} catch (error) {
  configurationError = error
}

const KEY  = import.meta.env.VITE_API_KEY || ''

function endpoint(path) {
  if (configurationError) throw configurationError
  return `${BASE}${path}`
}

function headers() {
  const h = { 'Content-Type': 'application/json' }
  if (KEY) h['Authorization'] = `Bearer ${KEY}`
  return h
}

function adminHeaders(adminKey) {
  const key = adminKey || sessionStorage.getItem('sr_admin_key')
  const h = { 'Content-Type': 'application/json' }
  if (key) h['X-Admin-Key'] = key
  return h
}

async function readJson(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`)
  return data
}

export async function checkHealth() {
  const res = await fetch(endpoint('/healthz'), { headers: headers() })
  if (!res.ok) throw new Error(`Health check failed (HTTP ${res.status})`)
  return res.json()
}

export async function sendFeedback(requestId, tags, note) {
  const res = await fetch(endpoint('/v1/feedback'), {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ request_id: requestId, tags, note }),
  })
  return res.ok ? res.json() : null
}

export async function createSession() {
  const res = await fetch(endpoint('/v1/sessions'), {
    method: 'POST',
    headers: headers(),
  })
  return res.ok ? res.json() : null
}

export async function fetchSessions(limit = 50, offset = 0) {
  const p = new URLSearchParams()
  if (limit) p.set('limit', String(limit))
  if (offset) p.set('offset', String(offset))
  const res = await fetch(endpoint(`/v1/sessions?${p.toString()}`), { headers: headers() })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchSessionHistory(sessionId) {
  const res = await fetch(endpoint(`/v1/sessions/${sessionId}`), { headers: headers() })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`)
  }
  return res.json()
}


export async function sendSessionFeedback(sessionId, tags, note) {
  const res = await fetch(endpoint('/v1/session-feedback'), {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ session_id: sessionId, tags, note }),
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new Error(data?.detail || `Feedback failed (HTTP ${res.status})`)
  return data
}

export async function fetchUsage(requestId) {
  const res = await fetch(endpoint(`/v1/usage/${requestId}`), { headers: headers() })
  if (!res.ok) return null
  return res.json()
}

export async function sendChat(messages, policy, forceTier, sessionId, classifierVersion) {
  const res = await fetch(`${BASE}/v1/chat/completions`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      model: 'auto',
      messages,
      smartroute: {
        policy: policy || null,
        force_tier: forceTier || null,
        session_id: sessionId || null,
        allow_tier_downgrade: true,
        classifier_version: classifierVersion || null,
      },
    }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw createApiError(res, data)
  const costHeader = res.headers.get('X-SR-Cost-USD')
  if (costHeader && data.smartroute) data.smartroute.cost_usd = parseFloat(costHeader)
  return data
}

export async function sendChatStream(messages, policy, forceTier, sessionId, classifierVersion) {
  const res = await fetch(endpoint('/v1/chat/completions'), {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      model: 'auto',
      messages,
      stream: true,
      smartroute: {
        policy: policy || null,
        force_tier: forceTier || null,
        session_id: sessionId || null,
        allow_tier_downgrade: true,
        classifier_version: classifierVersion || null,
      },
    }),
  })
  if (!res.ok) {
    throw await readApiError(res)
  }
  return res
}

// ─── Admin API (X-Admin-Key, xem issue #156/#155) ───────────────────────────

export class AdminAuthError extends Error {
  constructor() {
    super('Cần Admin Key hợp lệ.')
    this.name = 'AdminAuthError'
  }
}

async function _adminFetch(path) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10_000)
  let res
  try {
    res = await fetch(endpoint(path), { headers: adminHeaders(), signal: controller.signal })
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('Yêu cầu quá hạn (10s), vui lòng thử lại.')
    throw e
  } finally {
    clearTimeout(timer)
  }
  const data = await res.json().catch(() => null)
  if (res.status === 401 || res.status === 403) {
    // Clear stored key so stale credentials don't persist (#222)
    sessionStorage.removeItem('sr_admin_key')
    throw new AdminAuthError()
  }
  if (!res.ok) throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`)
  return data
}

export async function fetchAdminStats(from, to) {
  const p = new URLSearchParams()
  if (from) p.set('from', from)
  if (to) p.set('to', to)
  return _adminFetch(`/admin/stats?${p.toString()}`)
}

export async function fetchAdminLogs(from, to, limit = 50) {
  const p = new URLSearchParams()
  if (from) p.set('from', from)
  if (to) p.set('to', to)
  p.set('limit', String(limit))
  return _adminFetch(`/admin/logs?${p.toString()}`)
}

export async function fetchAdminRequests({ page = 1, pageSize = 50, from, to, tier, provider, status, minFallback, q } = {}) {
  const p = new URLSearchParams()
  if (page) p.set('page', String(page))
  if (pageSize) p.set('page_size', String(pageSize))
  if (from) p.set('from', from)
  if (to) p.set('to', to)
  if (tier) p.set('tier', tier)
  if (provider) p.set('provider', provider)
  if (status) p.set('status', status)
  if (minFallback != null && minFallback !== '') p.set('min_fallback', String(minFallback))
  if (q) p.set('q', q)
  return _adminFetch(`/admin/requests?${p.toString()}`)
}

export async function fetchAdminRequestDetail(id) {
  return _adminFetch(`/admin/requests/${id}`)
}

export function fetchAdminConfig() {
  return _adminFetch('/admin/config')
}

export async function updateAdminConfig(patch) {
  const res = await fetch(endpoint('/admin/config'), {
    method: 'PUT',
    headers: adminHeaders(),
    body: JSON.stringify(patch),
  })
  const data = await res.json().catch(() => null)
  if (res.status === 401 || res.status === 403) throw new AdminAuthError()
  if (!res.ok) throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`)
  return data
}

export async function fetchApiKeys(adminKey) {
  const res = await fetch(endpoint('/admin/keys'), { headers: adminHeaders(adminKey) })
  if (res.status === 401 || res.status === 403) {
    sessionStorage.removeItem('sr_admin_key')
    throw new AdminAuthError()
  }
  return readJson(res)
}

export async function createApiKey(adminKey, name, rateLimitPerMin) {
  const res = await fetch(endpoint('/admin/keys'), {
    method: 'POST',
    headers: adminHeaders(adminKey),
    body: JSON.stringify({ name, rate_limit_per_min: rateLimitPerMin }),
  })
  if (res.status === 401 || res.status === 403) {
    sessionStorage.removeItem('sr_admin_key')
    throw new AdminAuthError()
  }
  return readJson(res)
}

export async function revokeApiKey(adminKey, keyId) {
  const res = await fetch(endpoint(`/admin/keys/${keyId}`), {
    method: 'DELETE',
    headers: adminHeaders(adminKey),
  })
  if (res.status === 401 || res.status === 403) {
    sessionStorage.removeItem('sr_admin_key')
    throw new AdminAuthError()
  }
  return readJson(res)
}

// ─── User Authentication & Personalization API (HttpOnly Cookie) ────────────

export async function register(email, password, fullName) {
  const res = await fetch(endpoint('/v1/auth/register'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password, full_name: fullName || null }),
  })
  return readJson(res)
}

export async function login(email, password) {
  const res = await fetch(endpoint('/v1/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  })
  return readJson(res)
}

export async function logout() {
  const res = await fetch(endpoint('/v1/auth/logout'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
  return readJson(res)
}

export async function getMe() {
  const res = await fetch(endpoint('/v1/auth/me'), {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
  if (res.status === 401) return null
  return readJson(res)
}

export async function updatePreferences(preferences) {
  const res = await fetch(endpoint('/v1/auth/preferences'), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(preferences),
  })
  return readJson(res)
}

export async function fetchUserKeys() {
  const res = await fetch(endpoint('/v1/user/keys'), {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
  return readJson(res)
}

export async function createUserKey(name, rateLimitPerMin) {
  const res = await fetch(endpoint('/v1/user/keys'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ name, rate_limit_per_min: rateLimitPerMin }),
  })
  return readJson(res)
}

export async function revokeUserKey(keyId) {
  const res = await fetch(endpoint(`/v1/user/keys/${keyId}`), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  })
  return readJson(res)
}

