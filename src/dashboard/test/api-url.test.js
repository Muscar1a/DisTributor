import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeApiUrl } from '../src/api-url.js'

test('normalizes a gateway origin', () => {
  assert.equal(normalizeApiUrl('https://gateway.example.com/'), 'https://gateway.example.com')
})

test('rejects a URL path so secrets cannot be embedded in the API base', () => {
  assert.throws(
    () => normalizeApiUrl('https://dashboard.example.com/sr-secret'),
    /origin only/,
  )
})

test('rejects credentials, query parameters, and fragments', () => {
  assert.throws(() => normalizeApiUrl('https://admin:secret@gateway.example.com'), /credentials/)
  assert.throws(() => normalizeApiUrl('https://gateway.example.com?key=secret'), /query/)
  assert.throws(() => normalizeApiUrl('https://gateway.example.com/#secret'), /fragments/)
})

test('requires HTTPS in production', () => {
  assert.throws(
    () => normalizeApiUrl('http://gateway.example.com', { production: true }),
    /HTTPS/,
  )
})

test('rejects the Vercel frontend as the production API origin', () => {
  assert.throws(
    () => normalizeApiUrl('https://dashboard.example.com', {
      production: true,
      pageOrigin: 'https://dashboard.example.com',
    }),
    /Render gateway/,
  )
})

test('accepts a separate production gateway origin', () => {
  assert.equal(
    normalizeApiUrl('https://gateway.onrender.com', {
      production: true,
      pageOrigin: 'https://dashboard.vercel.app',
    }),
    'https://gateway.onrender.com',
  )
})
