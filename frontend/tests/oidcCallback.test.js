/**
 * S7 / F11 — the SSO callback must not carry credentials in the URL.
 *
 * The server now hands back a one-time opaque code in the fragment; the view
 * trades it for the token pair over `POST /auth/oidc/exchange`, which the
 * server only honours for the browser holding the HttpOnly nonce cookie —
 * hence `withCredentials`. This suite pins the three properties that make the
 * forged-link attack (`/oidc-callback#access_token=…`) inert: no token is ever
 * read from the URL, the exchange is credentialed, and a refused exchange
 * stores nothing.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const wsConnect = vi.fn()
vi.mock('../src/stores/websocket', () => ({
  useWebSocketStore: () => ({ connect: wsConnect }),
}))

import api from '../src/api/client'
import OidcCallbackView from '../src/views/OidcCallbackView.vue'

async function flush() {
  await new Promise((r) => setTimeout(r, 0))
  await new Promise((r) => setTimeout(r, 0))
}

async function mountView(hash) {
  window.history.replaceState({}, '', `/oidc-callback${hash}`)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
  router.push('/')
  await router.isReady()
  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })
  const wrapper = mount(OidcCallbackView, {
    global: { plugins: [router, i18n, createPinia()] },
  })
  await flush()
  return wrapper
}

describe('OidcCallbackView — one-time code handoff', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('exchanges the code with credentials and stores the returned tokens', async () => {
    api.post.mockResolvedValue({
      data: { access_token: 'access-abc', refresh_token: 'refresh-abc' },
    })
    api.get.mockResolvedValue({ data: { id: 'u1', username: 'sso' } })

    await mountView('#code=one-time-code')

    expect(api.post).toHaveBeenCalledWith(
      '/auth/oidc/exchange',
      { code: 'one-time-code' },
      { withCredentials: true },
    )
    expect(localStorage.getItem('access_token')).toBe('access-abc')
    expect(localStorage.getItem('refresh_token')).toBe('refresh-abc')
    expect(wsConnect).toHaveBeenCalled()
    // The code is wiped from the URL before it can reach history or a Referer.
    expect(window.location.hash).toBe('')
  })

  it('ignores tokens planted in the fragment', async () => {
    const wrapper = await mountView('#access_token=attacker-jwt&refresh_token=attacker-refresh')

    expect(api.post).not.toHaveBeenCalled()
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    expect(wrapper.text()).toContain(en.oidc.missing_params)
  })

  it('stores nothing when the server refuses the exchange', async () => {
    api.post.mockRejectedValue(new Error('401'))

    const wrapper = await mountView('#code=forged-code')

    expect(localStorage.getItem('access_token')).toBeNull()
    expect(wsConnect).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(en.oidc.exchange_failed)
  })
})
