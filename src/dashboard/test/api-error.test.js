import test from 'node:test'
import assert from 'node:assert/strict'

import { createApiError, formatPlaygroundError } from '../src/api-error.js'

function response(status, headers = {}) {
  const normalized = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]))
  return {
    status,
    headers: { get: name => normalized[name.toLowerCase()] ?? null },
  }
}

test('preserves structured daily quota metadata', () => {
  const error = createApiError(response(429, { 'Retry-After': '60' }), {
    error: {
      message: 'Quota exceeded',
      type: 'quota_exceeded',
      code: 'daily_token_budget_exceeded',
      request_id: 'request-1',
      reset_at: '2026-08-30T00:00:00Z',
      retry_after_seconds: 3600,
      details: { limit: 50000, used: 50997 },
    },
  })

  assert.equal(error.status, 429)
  assert.equal(error.code, 'daily_token_budget_exceeded')
  assert.equal(error.errorType, 'quota_exceeded')
  assert.equal(error.resetAt, '2026-08-30T00:00:00Z')
  assert.equal(error.retryAfterSeconds, 3600)
  assert.deepEqual(error.details, { limit: 50000, used: 50997 })
})

test('falls back to Retry-After header when body metadata is absent', () => {
  const error = createApiError(response(429, { 'Retry-After': '90' }), {
    error: { message: 'Slow down', code: 'rate_limit_exceeded' },
  })

  assert.equal(error.retryAfterSeconds, 90)
  assert.equal(formatPlaygroundError(error), 'Slow down')
})

test('formats quota reset in the requested local timezone', () => {
  const error = createApiError(response(429), {
    error: {
      message: 'Quota exceeded',
      code: 'daily_token_budget_exceeded',
      reset_at: '2026-08-30T00:00:00Z',
      retry_after_seconds: 3600,
    },
  })

  const message = formatPlaygroundError(error, { locale: 'vi-VN', timeZone: 'Asia/Ho_Chi_Minh' })
  assert.match(message, /Tài khoản demo đã hết quota/)
  assert.match(message, /07:00/)
  assert.match(message, /sử dụng API key khác/)
})

test('uses a relative retry duration when reset timestamp is malformed', () => {
  const error = createApiError(response(429), {
    error: {
      code: 'daily_token_budget_exceeded',
      reset_at: 'not-a-date',
      retry_after_seconds: 121,
    },
  })

  assert.match(formatPlaygroundError(error), /3 phút/)
})
