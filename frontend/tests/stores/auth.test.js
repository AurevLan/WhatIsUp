import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// JWT helper: build a token whose `exp` is in the future or the past.
function makeToken(expSecondsFromNow) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ sub: 'user-1', exp: Math.floor(Date.now() / 1000) + expSecondsFromNow }))
  return `${header}.${payload}.sig`
}

const apiPost = vi.fn()
const apiGet = vi.fn()
const axiosPost = vi.fn()

vi.mock('../../src/api/client', () => ({
  default: { post: (...a) => apiPost(...a), get: (...a) => apiGet(...a) },
}))
vi.mock('axios', () => ({
  default: { post: (...a) => axiosPost(...a) },
}))
vi.mock('../../src/lib/serverConfig', () => ({
  apiBaseUrl: () => 'http://api.example/api/v1',
  isNative: () => false,
}))
vi.mock('../../src/lib/biometricAuth', () => ({
  disableBiometric: vi.fn(async () => {}),
  isBiometricAvailable: vi.fn(async () => false),
  isBiometricEnabled: () => false,
  syncRefreshToken: vi.fn(async () => {}),
  unlockRefreshToken: vi.fn(async () => null),
}))

import { useAuthStore } from '../../src/stores/auth'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  apiPost.mockReset()
  apiGet.mockReset()
  axiosPost.mockReset()
})

afterEach(() => {
  localStorage.clear()
})

describe('auth store', () => {
  it('starts unauthenticated when no token in storage', () => {
    const auth = useAuthStore()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBe(null)
  })

  it('login persists tokens and fetches user profile', async () => {
    apiPost.mockResolvedValueOnce({ data: { access_token: 'a-token', refresh_token: 'r-token' } })
    apiGet.mockResolvedValueOnce({ data: { id: 'u1', email: 'a@b.c', is_superadmin: false } })

    const auth = useAuthStore()
    await auth.login('a@b.c', 'pwd')

    expect(localStorage.getItem('access_token')).toBe('a-token')
    expect(localStorage.getItem('refresh_token')).toBe('r-token')
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.isSuperadmin).toBe(false)
    expect(auth.user.email).toBe('a@b.c')

    // login uses x-www-form-urlencoded form for /auth/login
    expect(apiPost).toHaveBeenCalledWith('/auth/login', expect.any(URLSearchParams))
  })

  it('isSuperadmin reflects the user payload flag', async () => {
    apiPost.mockResolvedValueOnce({ data: { access_token: 't', refresh_token: 'r' } })
    apiGet.mockResolvedValueOnce({ data: { id: 'u', is_superadmin: true } })

    const auth = useAuthStore()
    await auth.login('a@b.c', 'p')
    expect(auth.isSuperadmin).toBe(true)
  })

  it('logout calls API and clears tokens + user', async () => {
    localStorage.setItem('access_token', 't')
    localStorage.setItem('refresh_token', 'r')
    apiPost.mockResolvedValueOnce({ data: {} })

    const auth = useAuthStore()
    auth.user = { id: 'u' }
    await auth.logout()

    expect(apiPost).toHaveBeenCalledWith('/auth/logout', { refresh_token: 'r' })
    expect(localStorage.getItem('access_token')).toBe(null)
    expect(localStorage.getItem('refresh_token')).toBe(null)
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBe(null)
  })

  it('logout swallows API errors and still clears local state', async () => {
    localStorage.setItem('access_token', 't')
    localStorage.setItem('refresh_token', 'r')
    apiPost.mockRejectedValueOnce(new Error('network'))

    const auth = useAuthStore()
    await auth.logout()

    expect(localStorage.getItem('access_token')).toBe(null)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('init refreshes when access token is expired and the refresh succeeds', async () => {
    localStorage.setItem('access_token', makeToken(-60))   // expired 1 min ago
    localStorage.setItem('refresh_token', 'r-token')
    axiosPost.mockResolvedValueOnce({ data: { access_token: 'new-token', refresh_token: 'new-r' } })
    apiGet.mockResolvedValueOnce({ data: { id: 'u' } })

    const auth = useAuthStore()
    await auth.init()

    expect(axiosPost).toHaveBeenCalledWith(
      'http://api.example/api/v1/auth/refresh',
      { refresh_token: 'r-token' },
    )
    expect(localStorage.getItem('access_token')).toBe('new-token')
    expect(auth.isAuthenticated).toBe(true)
  })

  it('init logs out when refresh fails', async () => {
    localStorage.setItem('access_token', makeToken(-60))
    localStorage.setItem('refresh_token', 'r-token')
    axiosPost.mockRejectedValueOnce(new Error('401'))
    apiPost.mockResolvedValueOnce({ data: {} }) // /auth/logout

    const auth = useAuthStore()
    await auth.init()

    expect(localStorage.getItem('access_token')).toBe(null)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('init logs out when /auth/me fails after refresh', async () => {
    localStorage.setItem('access_token', makeToken(60))   // not expired
    localStorage.setItem('refresh_token', 'r')
    apiGet.mockRejectedValueOnce(new Error('revoked'))
    apiPost.mockResolvedValueOnce({ data: {} })           // logout

    const auth = useAuthStore()
    await auth.init()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBe(null)
  })

  it('login with mfa_required sets mfaPending without storing tokens', async () => {
    apiPost.mockResolvedValueOnce({ data: { mfa_required: true, mfa_token: 'mfa-xyz' } })

    const auth = useAuthStore()
    await auth.login('a@b.c', 'pwd')

    expect(auth.mfaPending).toBe(true)
    expect(auth.mfaToken).toBe('mfa-xyz')
    expect(auth.isAuthenticated).toBe(false)
    expect(localStorage.getItem('access_token')).toBe(null)
    expect(localStorage.getItem('refresh_token')).toBe(null)
    // /auth/me must NOT be fetched while the challenge is pending
    expect(apiGet).not.toHaveBeenCalled()
  })

  it('verifyTotp exchanges the code for tokens and clears mfa state', async () => {
    // First the login challenge…
    apiPost.mockResolvedValueOnce({ data: { mfa_required: true, mfa_token: 'mfa-xyz' } })
    const auth = useAuthStore()
    await auth.login('a@b.c', 'pwd')

    // …then the TOTP verification returns real tokens + profile.
    apiPost.mockResolvedValueOnce({ data: { access_token: 'a-token', refresh_token: 'r-token' } })
    apiGet.mockResolvedValueOnce({ data: { id: 'u1', email: 'a@b.c', totp_enabled: true } })

    await auth.verifyTotp('123456')

    expect(apiPost).toHaveBeenLastCalledWith('/auth/totp/verify', { mfa_token: 'mfa-xyz', code: '123456' })
    expect(localStorage.getItem('access_token')).toBe('a-token')
    expect(localStorage.getItem('refresh_token')).toBe('r-token')
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.user.email).toBe('a@b.c')
    expect(auth.mfaPending).toBe(false)
    expect(auth.mfaToken).toBe(null)
  })

  it('init is a no-op when no tokens are stored at all', async () => {
    const auth = useAuthStore()
    await auth.init()

    expect(apiGet).not.toHaveBeenCalled()
    expect(axiosPost).not.toHaveBeenCalled()
    expect(auth.isAuthenticated).toBe(false)
  })
})
