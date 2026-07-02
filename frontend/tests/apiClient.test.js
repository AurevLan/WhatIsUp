/**
 * Tests for the global error-toast interceptor in api/client.js.
 *
 * The interceptor fires for every failed HTTP request and shows a toast,
 * except when:
 *   • status is 401  (handled upstream by the token-refresh interceptor)
 *   • the caller passes { skipErrorToast: true } in the axios request config
 *
 * Strategy: mock axios so api.interceptors.response.use() captures the
 * registered handlers; then call the handlers directly in each test.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// ── Hoisted state (must be initialised before vi.mock() factories run) ────────
// vi.hoisted() runs synchronously before all vi.mock() factories and imports,
// so the variables are safe to reference inside the mock factory below.

const { toastError, responseHandlers } = vi.hoisted(() => {
  const toastError = vi.fn()
  const responseHandlers = []
  return { toastError, responseHandlers }
})

// ── Mocks (hoisted by vitest before any static imports) ──────────────────────

vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ error: toastError }),
}))

vi.mock('../src/i18n', () => ({
  i18n: { global: { t: (key) => key } },
}))

vi.mock('../src/router', () => ({
  default: { push: vi.fn() },
}))

vi.mock('../src/lib/serverConfig', () => ({
  apiBaseUrl: () => '',
}))

// Capture both response interceptors that client.js registers.
vi.mock('axios', () => {
  const mockInstance = {
    interceptors: {
      request: { use: vi.fn() },
      response: {
        use: vi.fn((ok, err) => {
          responseHandlers.push({ ok, err })
        }),
      },
    },
  }
  return {
    default: {
      // axios.create() → returns our mock instance
      create: vi.fn(() => mockInstance),
      // axios.post() is called by the 401-refresh flow; make it reject so that
      // flow falls through and the original 401 error is re-thrown.
      post: vi.fn().mockRejectedValue(new Error('refresh failed')),
    },
  }
})

// Importing client.js triggers axios.create() and registers the interceptors.
// The responseHandlers array is populated as a side-effect of this import.
import '../src/api/client.js'

// ── Helpers ──────────────────────────────────────────────────────────────────

// The toast interceptor is registered second (after the 401-refresh interceptor).
function getToastHandler() {
  // responseHandlers[0] = 401-refresh interceptor
  // responseHandlers[1] = global-toast interceptor
  return responseHandlers[1]
}

function mkError(overrides = {}) {
  return { config: {}, response: null, code: null, ...overrides }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('api/client.js — global error toast interceptor', () => {
  beforeEach(() => {
    toastError.mockClear()
  })

  // ── Success path ─────────────────────────────────────────────────────────

  it('passes successful responses through without toasting', async () => {
    const { ok } = getToastHandler()
    const resp = { data: { id: 1 }, status: 200 }
    const result = await ok(resp)
    expect(result).toBe(resp)
    expect(toastError).not.toHaveBeenCalled()
  })

  // ── Error toasting ───────────────────────────────────────────────────────

  it('shows an error toast for a 500 server error', async () => {
    const { err } = getToastHandler()
    const error = mkError({ response: { status: 500, data: {} } })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('errors.server')
  })

  it('shows an error toast for a 4xx client error', async () => {
    const { err } = getToastHandler()
    const error = mkError({ response: { status: 403, data: {} } })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('errors.request')
  })

  it('uses the FastAPI detail string when present and ≤ 200 chars', async () => {
    const { err } = getToastHandler()
    const error = mkError({
      response: { status: 400, data: { detail: 'Monitor name already exists' } },
    })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('Monitor name already exists')
  })

  it('falls back to the generic key when detail is a list (validation errors)', async () => {
    const { err } = getToastHandler()
    const error = mkError({
      response: { status: 422, data: { detail: [{ msg: 'field required', loc: ['body', 'name'] }] } },
    })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('errors.request')
  })

  it('falls back to the generic key when detail exceeds 200 chars', async () => {
    const { err } = getToastHandler()
    const longDetail = 'x'.repeat(201)
    const error = mkError({ response: { status: 500, data: { detail: longDetail } } })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('errors.server')
  })

  it('shows a network error toast when there is no response', async () => {
    const { err } = getToastHandler()
    const error = mkError({ response: null, code: 'ERR_NETWORK' })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('errors.network')
  })

  it('shows a timeout toast for ECONNABORTED', async () => {
    const { err } = getToastHandler()
    const error = mkError({ response: null, code: 'ECONNABORTED' })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledWith('errors.timeout')
  })

  // ── Opt-out ──────────────────────────────────────────────────────────────

  it('skips the toast when skipErrorToast is true', async () => {
    const { err } = getToastHandler()
    const error = mkError({
      config: { skipErrorToast: true },
      response: { status: 500, data: {} },
    })
    await err(error).catch(() => {})
    expect(toastError).not.toHaveBeenCalled()
  })

  it('shows the toast when skipErrorToast is false', async () => {
    const { err } = getToastHandler()
    const error = mkError({
      config: { skipErrorToast: false },
      response: { status: 500, data: {} },
    })
    await err(error).catch(() => {})
    expect(toastError).toHaveBeenCalledOnce()
  })

  // ── 401 handling ─────────────────────────────────────────────────────────

  it('skips the toast for 401 (handled by the refresh flow)', async () => {
    const { err } = getToastHandler()
    const error = mkError({ response: { status: 401, data: {} } })
    await err(error).catch(() => {})
    expect(toastError).not.toHaveBeenCalled()
  })

  // ── Error propagation ────────────────────────────────────────────────────

  it('always rejects the promise so callers can still catch', async () => {
    const { err } = getToastHandler()
    const error = mkError({ response: { status: 503, data: {} } })
    await expect(err(error)).rejects.toBe(error)
  })
})
