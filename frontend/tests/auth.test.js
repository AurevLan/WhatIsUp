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
    },
  }
})

import { useAuthStore } from '../src/stores/auth'

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
    it('fetches user when token exists', async () => {
      store.accessToken = 'at-valid'
      axios.get.mockResolvedValue({
        data: { id: 'u-1', email: 'init@test.com', is_superadmin: true },
      })

      await store.init()
      expect(store.user.email).toBe('init@test.com')
      expect(store.isSuperadmin).toBe(true)
    })

    it('logs out on 401 during init', async () => {
      store.accessToken = 'at-expired'
      axios.get.mockRejectedValue({ response: { status: 401 } })

      await store.init()
      expect(store.user).toBeNull()
      expect(store.accessToken).toBeNull()
    })

    it('does nothing when no token', async () => {
      await store.init()
      expect(axios.get).not.toHaveBeenCalled()
      expect(store.user).toBeNull()
    })
  })
})
