// Persistable filters for list views.
//
// Given a reactive state object, this composable keeps it in sync with:
//   1. The URL querystring (so filters are shareable / bookmarkable)
//   2. localStorage under `whatisup_filter:{key}` (so F5 and re-navigation
//      restore the last filters per view)
//
// Initial value priority: URL query → localStorage → defaults.
// A call to `reset()` wipes both and restores defaults.

import { reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const STORAGE_PREFIX = 'whatisup_filter:'

function storageKey(viewKey) {
  return `${STORAGE_PREFIX}${viewKey}`
}

// Serialize a single value to a query-string-safe string.
function serializeValue(v) {
  if (v == null) return null
  if (Array.isArray(v)) {
    const filtered = v.filter((x) => x != null && x !== '')
    return filtered.length ? filtered.join(',') : null
  }
  if (typeof v === 'boolean') return v ? '1' : '0'
  const s = String(v)
  return s === '' ? null : s
}

// Deserialize a query/localStorage value back to the original shape,
// inferred from the default value's type.
function deserializeValue(raw, defaultValue) {
  if (raw == null) return defaultValue
  if (Array.isArray(defaultValue)) {
    return String(raw).split(',').filter(Boolean)
  }
  if (typeof defaultValue === 'number') {
    const n = Number(raw)
    return Number.isFinite(n) ? n : defaultValue
  }
  if (typeof defaultValue === 'boolean') {
    return raw === '1' || raw === 'true'
  }
  return String(raw)
}

function readFromRoute(route, defaults, prefix) {
  const out = {}
  let any = false
  for (const [key, def] of Object.entries(defaults)) {
    const param = prefix ? `${prefix}_${key}` : key
    if (param in route.query) {
      out[key] = deserializeValue(route.query[param], def)
      any = true
    }
  }
  return any ? out : null
}

function readFromStorage(viewKey, defaults) {
  if (typeof localStorage === 'undefined') return null
  try {
    const raw = localStorage.getItem(storageKey(viewKey))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    const out = {}
    for (const [key, def] of Object.entries(defaults)) {
      if (key in parsed) out[key] = deserializeValue(parsed[key], def)
    }
    return Object.keys(out).length ? out : null
  } catch {
    return null
  }
}

/**
 * @param {string} viewKey      Stable identifier for this view (e.g. "monitors", "incidents")
 * @param {object} defaults     Default filter values (plain object, flat)
 * @param {object} [options]
 * @param {string} [options.prefix]   Query-param prefix (default = none; avoid collisions
 *                                    if the same page has several filter groups)
 * @returns {{ state: object, reset: () => void }}
 */
export function useFilterPreset(viewKey, defaults, options = {}) {
  const route = useRoute()
  const router = useRouter()
  const prefix = options.prefix || ''

  // 1. URL query wins, 2. localStorage, 3. defaults
  const initial = { ...defaults }
  const fromRoute = readFromRoute(route, defaults, prefix)
  const fromStorage = fromRoute ? null : readFromStorage(viewKey, defaults)
  Object.assign(initial, fromStorage || {}, fromRoute || {})

  const state = reactive(initial)

  // Debounce writes so rapid typing doesn't spam history entries.
  let pendingWrite = null
  const persist = () => {
    if (pendingWrite) return
    pendingWrite = setTimeout(() => {
      pendingWrite = null
      const query = { ...route.query }
      const storageSnapshot = {}
      for (const [key, def] of Object.entries(defaults)) {
        const param = prefix ? `${prefix}_${key}` : key
        const s = serializeValue(state[key])
        const defS = serializeValue(def)
        if (s == null || s === defS) {
          delete query[param]
        } else {
          query[param] = s
        }
        storageSnapshot[key] = s == null ? def : state[key]
      }
      router.replace({ query }).catch(() => {})
      if (typeof localStorage !== 'undefined') {
        try {
          localStorage.setItem(storageKey(viewKey), JSON.stringify(storageSnapshot))
        } catch {
          /* quota / private mode — ignore */
        }
      }
    }, 120)
  }

  watch(state, persist, { deep: true })

  const reset = () => {
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(storageKey(viewKey))
    }
    for (const [key, def] of Object.entries(defaults)) {
      state[key] = Array.isArray(def) ? [...def] : def
    }
    const query = { ...route.query }
    for (const key of Object.keys(defaults)) {
      const param = prefix ? `${prefix}_${key}` : key
      delete query[param]
    }
    router.replace({ query }).catch(() => {})
  }

  return { state, reset }
}
