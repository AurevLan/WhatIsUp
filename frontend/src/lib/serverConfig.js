// Runtime backend URL resolver.
//
// Web build → empty base, axios uses relative '/api/v1' (nginx proxies).
// Native build (Capacitor) → user-provided URL stored in localStorage.
// Until configured, isConfigured() returns false and the router redirects to /setup.

const STORAGE_KEY = 'whatisup_server_url'

export function isNative() {
  return typeof window !== 'undefined' && window.Capacitor?.isNativePlatform?.() === true
}

export function getServerUrl() {
  if (typeof localStorage === 'undefined') return ''
  const stored = localStorage.getItem(STORAGE_KEY) || ''
  if (!stored) return ''
  // Mixed-content guard: a stored HTTP URL is unusable when the page is HTTPS,
  // and every axios call would be blocked. Discard it silently.
  if (
    typeof window !== 'undefined'
    && window.location?.protocol === 'https:'
    && stored.startsWith('http://')
  ) {
    localStorage.removeItem(STORAGE_KEY)
    return ''
  }
  return stored
}

export function setServerUrl(url) {
  const trimmed = String(url || '').trim().replace(/\/+$/, '')
  if (!trimmed) throw new Error('empty server url')
  if (!/^https?:\/\//i.test(trimmed)) throw new Error('url must start with http(s)://')
  localStorage.setItem(STORAGE_KEY, trimmed)
}

export function clearServerUrl() {
  localStorage.removeItem(STORAGE_KEY)
}

export function isConfigured() {
  return !isNative() || !!getServerUrl()
}

export function apiBaseUrl() {
  const base = getServerUrl()
  return base ? `${base}/api/v1` : '/api/v1'
}

export function wsBaseUrl() {
  const base = getServerUrl()
  if (base) return base.replace(/^http/i, 'ws')
  if (typeof window === 'undefined') return ''
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}`
}
