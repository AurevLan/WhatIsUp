/**
 * Tests for the auth Pinia store and API client interceptors.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import axios from 'axios'

vi.mock('axios', async () => {
  return {
    default: {
      get: vi.fn(),
      post: vi.fn(),
      create: vi.fn(() => ({
        get: vi.fn(),
        post: vi.fn(),
        interceptors: {
          request: { use: vi.fn() },
          response: { use: vi.fn() },
        },
      })),
    },
  }
})

// Mock the shared api client — auth store uses it for /auth/me on init
vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import { useAuthStore } from '../src/stores/auth'
import apiClient from '../src/api/client'

// Build a fake JWT whose `exp` claim is `secondsFromNow` in the future.
function makeJwt(secondsFromNow = 3600) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ sub: 'u-1', exp: Math.floor(Date.now() / 1000) + secondsFromNow }))
  return `${header}.${payload}.sig`
}

// ── localStorage mock ────────────────────────────────────────────────────────

const localStorageMock = (() => {
  let store = {}
  return {
    getItem: vi.fn((key) => store[key] ?? null),
    setItem: vi.fn((key, val) => { store[key] = String(val) }),
    removeItem: vi.fn((key) => { delete store[key] }),
    clear: () => { store = {} },
  }
})()

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

// ── Tests ────────────────────────────────────────────────────────────────────

describe('auth store', () => {
  let store

  beforeEach(() => {
    localStorageMock.clear()
    vi.clearAllMocks()
    setActivePinia(createPinia())
    store = useAuthStore()
  })

  // ── Computed properties ──────────────────────────────────────────────

  describe('computed properties', () => {
    it('isAuthenticated is false when no token', () => {
      expect(store.isAuthenticated).toBe(false)
    })

    it('isAuthenticated is true when token is set', () => {
      store.accessToken = 'some-token'
      expect(store.isAuthenticated).toBe(true)
    })

    it('isSuperadmin is false when no user', () => {
      expect(store.isSuperadmin).toBe(false)
    })

    it('isSuperadmin reflects user flag', () => {
      store.user = { is_superadmin: true }
      expect(store.isSuperadmin).toBe(true)

      store.user = { is_superadmin: false }
      expect(store.isSuperadmin).toBe(false)
    })
  })

  // ── login() ──────────────────────────────────────────────────────────

  describe('login', () => {
    it('stores tokens and fetches user info', async () => {
      axios.post.mockResolvedValue({
        data: { access_token: 'at-123', refresh_token: 'rt-456' },
      })
      axios.get.mockResolvedValue({
        data: { id: 'u-1', email: 'test@test.com', is_superadmin: false },
      })

      await store.login('test@test.com', 'pass')

      expect(store.accessToken).toBe('at-123')
      expect(store.user.email).toBe('test@test.com')
      expect(localStorageMock.setItem).toHaveBeenCalledWith('access_token', 'at-123')
      expect(localStorageMock.setItem).toHaveBeenCalledWith('refresh_token', 'rt-456')
    })

    it('sends credentials as form-urlencoded', async () => {
      axios.post.mockResolvedValue({
        data: { access_token: 'at', refresh_token: 'rt' },
      })
      axios.get.mockResolvedValue({ data: {} })

      await store.login('user@example.com', 'secret')

      const formData = axios.post.mock.calls[0][1]
      expect(formData.toString()).toContain('username=user%40example.com')
      expect(formData.toString()).toContain('password=secret')
    })
  })

  // ── logout() ─────────────────────────────────────────────────────────

  describe('logout', () => {
    it('clears user, token, and localStorage', async () => {
      store.user = { id: 'u-1' }
      store.accessToken = 'at-123'
      localStorageMock.setItem('refresh_token', 'rt-456')

      axios.post.mockResolvedValue({})
      await store.logout()

      expect(store.user).toBeNull()
      expect(store.accessToken).toBeNull()
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('access_token')
      expect(localStorageMock.removeItem).toHaveBeenCalledWith('refresh_token')
    })

    it('does not crash if logout API call fails', async () => {
      localStorageMock.setItem('refresh_token', 'rt-456')
      axios.post.mockRejectedValue(new Error('network'))

      await store.logout() // should not throw
      expect(store.user).toBeNull()
    })
  })

  // ── init() ───────────────────────────────────────────────────────────

  describe('init', () => {
    it('fetches user when access token is still valid', async () => {
      const validToken = makeJwt(3600)
      store.accessToken = validToken
      localStorage.setItem('access_token', validToken)
      apiClient.get.mockResolvedValue({
        data: { id: 'u-1', email: 'init@test.com', is_superadmin: true },
      })

      await store.init()
      expect(apiClient.get).toHaveBeenCalledWith('/auth/me')
      expect(store.user.email).toBe('init@test.com')
      expect(store.isSuperadmin).toBe(true)
    })

    it('rotates an expired access token via the refresh token on init', async () => {
      const expiredToken = makeJwt(-60)
      const freshToken = makeJwt(900)
      store.accessToken = expiredToken
      localStorage.setItem('access_token', expiredToken)
      localStorage.setItem('refresh_token', 'rt-valid')

      axios.post.mockResolvedValue({
        data: { access_token: freshToken, refresh_token: 'rt-fresh' },
      })
      apiClient.get.mockResolvedValue({
        data: { id: 'u-1', email: 'rotated@test.com', is_superadmin: false },
      })

      await store.init()
      expect(axios.post).toHaveBeenCalledWith(
        expect.stringContaining('/auth/refresh'),
        { refresh_token: 'rt-valid' }
      )
      expect(localStorage.getItem('access_token')).toBe(freshToken)
      expect(localStorage.getItem('refresh_token')).toBe('rt-fresh')
      expect(store.user.email).toBe('rotated@test.com')
    })

    it('logs out when access is expired and refresh also fails', async () => {
      const expiredToken = makeJwt(-60)
      store.accessToken = expiredToken
      localStorage.setItem('access_token', expiredToken)
      localStorage.setItem('refresh_token', 'rt-dead')

      axios.post.mockRejectedValue({ response: { status: 401 } })

      await store.init()
      expect(store.user).toBeNull()
      expect(store.accessToken).toBeNull()
      expect(localStorage.getItem('access_token')).toBeNull()
    })

    it('does nothing when no token', async () => {
      await store.init()
      expect(apiClient.get).not.toHaveBeenCalled()
      expect(store.user).toBeNull()
    })
  })
})
