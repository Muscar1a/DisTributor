export class ApiError extends Error {
  constructor(message, { status, code, errorType, requestId, resetAt, retryAfterSeconds, details } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.errorType = errorType
    this.requestId = requestId
    this.resetAt = resetAt
    this.retryAfterSeconds = retryAfterSeconds
    this.details = details || {}
  }
}

function positiveInteger(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.ceil(parsed) : null
}

export function createApiError(response, data = {}) {
  const payload = data?.error || {}
  const retryAfterSeconds = positiveInteger(payload.retry_after_seconds)
    ?? positiveInteger(response?.headers?.get?.('Retry-After'))

  return new ApiError(
    payload.message || data?.detail || `HTTP ${response?.status ?? 'error'}`,
    {
      status: response?.status,
      code: payload.code,
      errorType: payload.type,
      requestId: payload.request_id || response?.headers?.get?.('X-SR-Request-Id'),
      resetAt: payload.reset_at,
      retryAfterSeconds,
      details: payload.details,
    },
  )
}

export async function readApiError(response) {
  const data = await response.json().catch(() => ({}))
  return createApiError(response, data)
}

export function formatPlaygroundError(error, { locale = 'vi-VN', timeZone } = {}) {
  if (error?.code !== 'daily_token_budget_exceeded') return error?.message || 'Không thể hoàn tất yêu cầu.'

  let resetText = ''
  if (error.resetAt) {
    const resetDate = new Date(error.resetAt)
    if (!Number.isNaN(resetDate.getTime())) {
      const options = { dateStyle: 'medium', timeStyle: 'short' }
      if (timeZone) options.timeZone = timeZone
      resetText = ` Hạn mức dự kiến được làm mới lúc ${new Intl.DateTimeFormat(locale, options).format(resetDate)}.`
    }
  }

  if (!resetText && error.retryAfterSeconds) {
    const minutes = Math.max(1, Math.ceil(error.retryAfterSeconds / 60))
    resetText = ` Hạn mức dự kiến được làm mới sau khoảng ${minutes} phút.`
  }

  return `Tài khoản demo đã hết quota.${resetText} Vui lòng thử lại sau hoặc sử dụng API key khác.`
}
