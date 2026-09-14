import { normalizeApiUrl } from '../src/api-url.js'

const apiUrl = process.env.VITE_API_URL
const dashboardOrigin = process.env.VERCEL_PRODUCTION_ORIGIN

if (!dashboardOrigin) {
  console.error('::error::Set VERCEL_PRODUCTION_ORIGIN to the public Vercel dashboard origin.')
  process.exit(1)
}

try {
  const normalized = normalizeApiUrl(apiUrl, {
    production: true,
    pageOrigin: dashboardOrigin,
  })
  console.log(`Validated production gateway origin: ${normalized}`)
} catch (error) {
  console.error(`::error::${error.message}`)
  process.exit(1)
}
