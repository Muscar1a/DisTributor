export function normalizeApiUrl(rawValue, { production = false, pageOrigin = '' } = {}) {
  const candidate = String(rawValue || '').trim()
  if (!candidate) {
    throw new Error('VITE_API_URL is required for this deployment.')
  }

  let parsed
  try {
    parsed = new URL(candidate)
  } catch {
    throw new Error('VITE_API_URL must be an absolute HTTP(S) origin.')
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('VITE_API_URL must use HTTP or HTTPS.')
  }
  if (production && parsed.protocol !== 'https:') {
    throw new Error('VITE_API_URL must use HTTPS in production.')
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('VITE_API_URL must not contain credentials, query parameters, or fragments.')
  }
  if (parsed.pathname !== '/' && parsed.pathname !== '') {
    throw new Error('VITE_API_URL must be an origin only; do not include paths or secrets.')
  }

  if (production && pageOrigin) {
    let frontendOrigin
    try {
      frontendOrigin = new URL(pageOrigin).origin
    } catch {
      throw new Error('The production dashboard origin is invalid.')
    }
    if (parsed.origin === frontendOrigin) {
      throw new Error('VITE_API_URL must point to the Render gateway, not the Vercel dashboard.')
    }
  }

  return parsed.origin
}
